import Foundation
import CoreHost

/// The game's own numbers, read out of a serialised machine image.
///
/// This is the same decode as `server/save_state.py`, and the layout comes from
/// the same place: the save archive's own record format, checked there against
/// the shipped `game/RANGER.GRP`. A running machine keeps the working copy of
/// the shared bag in the 800 bytes immediately in front of the 320 character
/// records, and that copy is the one that moves when the player picks something
/// up.
///
/// Nothing here writes, and nothing here is reachable from the Control API. An
/// agent drives the game through keys, so the only way it can move these
/// numbers is by playing.
enum GameState {

    struct Progress: Equatable {
        var name = ""
        var level = 0
        var exp = 0
        var hp = 0
        var maxhp = 0
        var skills = 0
        var reputation = 0
        var potential = 0
        var items = 0
        var itemsDistinct = 0
        var books: [Int] = []
    }

    // Section 1: 320 records of 182 bytes, and the offsets inside one record.
    static let charSlots = 320
    static let charSize = 182
    static let charBytes = charSlots * charSize
    static let cName = 8, cLevel = 30, cExp = 32, cHP = 34, cMaxHP = 36
    static let cReputation = 118, cPotential = 120
    static let cSkillID = 126, cItem = 166, cItemCount = 174
    static let learnSkills = 10, carryItems = 4

    // Section 0's bag: 200 (id, count) pairs of int16.
    static let bagSlots = 200
    static let bagBytes = bagSlots * 4
    static let maxItemID = 199

    /// The fourteen novels that end the game, contiguous in the item table.
    static let bookIDs = Set(144...157)

    /// This NPC's name occurs once in the image, and two neighbours at the
    /// right stride confirm the hit: the names alone repeat, and the
    /// serialised layout moves between runs.
    private static let anchorName = "程靈素", anchorSlot = 2
    private static let confirm = [("胡斐", 1), ("苗人鳳", 3)]

    // MARK: - Big5

    private static let big5 = String.Encoding(rawValue: CFStringConvertEncodingToNSStringEncoding(
        CFStringEncoding(CFStringEncodings.big5.rawValue)))

    private static func big5Bytes(_ s: String) -> [UInt8] { Array(s.data(using: big5) ?? Data()) }

    static func big5Text(_ bytes: ArraySlice<UInt8>) -> String {
        let cut = bytes.prefix(while: { $0 != 0 })
        return String(data: Data(cut), encoding: big5) ?? ""
    }

    // MARK: - reader

    /// Serialises the machine and decodes it. Holding the located base between
    /// calls turns the scan into one comparison while a machine keeps running.
    final class Reader {
        private var buffer = [UInt8]()
        private var base: Int?

        func read() -> Progress? {
            let cap = core_state_size()
            guard cap > 0 else { return nil }
            if buffer.count < cap { buffer = [UInt8](repeating: 0, count: cap) }
            let written = buffer.withUnsafeMutableBufferPointer {
                core_state_copy($0.baseAddress, cap)
            }
            guard written > 0 else { return nil }
            let size = Int(written)

            if let at = base, !confirms(buffer, at, limit: size) { base = nil }
            if base == nil { base = locate(buffer, limit: size) }
            guard let charBase = base else { return nil }
            return decode(buffer, charBase: charBase, limit: size)
        }
    }

    // MARK: - decoding

    static func i16(_ m: [UInt8], _ at: Int) -> Int {
        Int(Int16(bitPattern: UInt16(m[at]) | UInt16(m[at + 1]) << 8))
    }

    private static func u16(_ m: [UInt8], _ at: Int) -> Int {
        Int(UInt16(m[at]) | UInt16(m[at + 1]) << 8)
    }

    private static func confirms(_ m: [UInt8], _ charBase: Int, limit: Int) -> Bool {
        guard charBase >= bagBytes, charBase + charBytes <= limit else { return false }
        for (name, slot) in confirm {
            let at = charBase + slot * charSize + cName
            let want = big5Bytes(name)
            guard at + want.count <= limit,
                  Array(m[at..<(at + want.count)]) == want else { return false }
        }
        return true
    }

    private static func locate(_ m: [UInt8], limit: Int) -> Int? {
        let pattern = big5Bytes(anchorName)
        guard !pattern.isEmpty else { return nil }
        var from = 0
        while let hit = find(m, pattern, from: from, limit: limit) {
            let candidate = hit - cName - anchorSlot * charSize
            if candidate >= 0, confirms(m, candidate, limit: limit) { return candidate }
            from = hit + 1
        }
        return nil
    }

    private static func find(_ m: [UInt8], _ pattern: [UInt8], from: Int, limit: Int) -> Int? {
        let last = limit - pattern.count
        guard last >= from else { return nil }
        let first = pattern[0]
        var i = max(0, from)
        while i <= last {
            if m[i] == first {
                var k = 1
                while k < pattern.count, m[i + k] == pattern[k] { k += 1 }
                if k == pattern.count { return i }
            }
            i += 1
        }
        return nil
    }

    /// `{item id: count}` for the working bag, or nil when the region is not
    /// one. Occupied slots pack at the front, so a gap followed by an entry
    /// means some unrelated 800 bytes matched.
    private static func bag(_ m: [UInt8], at start: Int) -> [Int: Int]? {
        var held: [Int: Int] = [:]
        var emptySeen = false
        for slot in 0..<bagSlots {
            let id = i16(m, start + slot * 4)
            let count = i16(m, start + slot * 4 + 2)
            if id == -1 && count == 0 { emptySeen = true; continue }
            if emptySeen || id < 0 || id > maxItemID || count <= 0 || held[id] != nil { return nil }
            held[id] = count
        }
        return held
    }

    private static func decode(_ m: [UInt8], charBase: Int, limit: Int) -> Progress? {
        guard charBase >= bagBytes, charBase + charSize <= limit,
              let held = bag(m, at: charBase - bagBytes) else { return nil }

        var p = Progress()
        p.name = big5Text(m[(charBase + cName)..<(charBase + cName + 10)])
        p.level = i16(m, charBase + cLevel)
        p.exp = u16(m, charBase + cExp)
        p.hp = i16(m, charBase + cHP)
        p.maxhp = i16(m, charBase + cMaxHP)
        p.reputation = i16(m, charBase + cReputation)
        p.potential = i16(m, charBase + cPotential)
        p.skills = (0..<learnSkills).filter { i16(m, charBase + cSkillID + $0 * 2) > 0 }.count
        p.items = held.values.reduce(0, +)
        p.itemsDistinct = held.count

        // A book counts once whether it sits in the bag or in the leader's
        // own four carried slots.
        var books = Set(held.keys).intersection(bookIDs)
        for k in 0..<carryItems {
            let id = i16(m, charBase + cItem + k * 2)
            let count = i16(m, charBase + cItemCount + k * 2)
            if id >= 0, count > 0, bookIDs.contains(id) { books.insert(id) }
        }
        p.books = books.sorted()
        return p
    }
}

extension GameState {

    /// Who is in the party, from an archive the game itself wrote.
    ///
    /// The roster and the world square are true only there: the copies of them
    /// in a machine image are the ones the game loaded when the run began, and
    /// they do not follow the player. Everything else the panel shows is read
    /// live out of the machine instead, which is fresher than any save.
    struct Party: Equatable {
        struct Member: Equatable {
            var name: String
            var level: Int
        }
        var members: [Member] = []
        var totalLevel: Int { members.reduce(0) { $0 + $1.level } }
        var onWorldMap = false
    }

    static let baseHeader = 12, teamSlots = 6
    static let baseBytes = baseHeader * 2 + teamSlots * 2 + bagBytes    // 836
    static let teamAt = baseHeader * 2

    /// `R<n>.GRP` split by `R<n>.IDX`, which is a list of section end offsets.
    static func party(grp: [UInt8], idx: [UInt8]) -> Party? {
        guard idx.count >= 24 else { return nil }
        var ends: [Int] = []
        for k in 0..<6 {
            ends.append(Int(UInt32(idx[k * 4]) | UInt32(idx[k * 4 + 1]) << 8
                            | UInt32(idx[k * 4 + 2]) << 16 | UInt32(idx[k * 4 + 3]) << 24))
        }
        guard ends[0] == baseBytes, ends[1] - ends[0] == charBytes,
              ends[1] <= grp.count else { return nil }
        var party = Party()
        // submap is the scene's id plus one, so zero is the world map itself.
        party.onWorldMap = i16(grp, 2) == 0
        for slot in 0..<teamSlots {
            let cid = i16(grp, teamAt + slot * 2)
            if cid < 0 { break }                    // occupied slots pack first
            guard 0 <= cid, cid < charSlots else { return nil }
            let at = ends[0] + cid * charSize
            party.members.append(Party.Member(
                name: big5Text(grp[(at + cName)..<(at + cName + 10)]),
                level: i16(grp, at + cLevel)))
        }
        return party.members.isEmpty ? nil : party
    }
}
