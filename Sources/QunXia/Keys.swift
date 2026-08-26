import Foundation

/// RETROK_* values. Only the subset a DOS game can actually receive.
enum RetroKey {
    static let table: [String: Int] = {
        var t: [String: Int] = [
            "backspace": 8, "tab": 9, "enter": 13, "return": 13,
            "pause": 19, "esc": 27, "escape": 27, "space": 32,
            "quote": 39, "comma": 44, "minus": 45, "period": 46, "slash": 47,
            "semicolon": 59, "equals": 61, "leftbracket": 91, "backslash": 92,
            "rightbracket": 93, "backquote": 96, "delete": 127,
            "up": 273, "down": 274, "right": 275, "left": 276,
            "insert": 277, "home": 278, "end": 279, "pageup": 280, "pagedown": 281,
            "numlock": 300, "capslock": 301, "scrolllock": 302,
            "rshift": 303, "shift": 304, "lshift": 304,
            "rctrl": 305, "ctrl": 306, "lctrl": 306,
            "ralt": 307, "alt": 308, "lalt": 308,
            "kpenter": 271, "kpplus": 270, "kpminus": 269,
            "kpmultiply": 268, "kpdivide": 267, "kpperiod": 266,
        ]
        for (i, c) in "abcdefghijklmnopqrstuvwxyz".enumerated() {
            t[String(c)] = 97 + i
        }
        for d in 0...9 { t[String(d)] = 48 + d }
        for f in 1...12 { t["f\(f)"] = 281 + f }
        for k in 0...9 { t["kp\(k)"] = 256 + k }
        // The four movement axes are screen diagonals in this isometric game,
        // and the numpad names match what you see. Verified identical to the
        // arrows on the real game, so these are aliases, not extra behaviour.
        t["kp7"] = 276; t["upleft"] = 276; t["nw"] = 276      // == left
        t["kp9"] = 273; t["upright"] = 273; t["ne"] = 273     // == up
        t["kp1"] = 274; t["downleft"] = 274; t["sw"] = 274    // == down
        t["kp3"] = 275; t["downright"] = 275; t["se"] = 275   // == right
        // Game-facing aliases used by the agent API.
        t["ok"] = 13
        t["confirm"] = 13
        t["cancel"] = 27
        t["back"] = 27
        t["yes"] = 121   // y
        t["no"] = 110    // n
        t["w"] = 119; t["a"] = 97; t["s"] = 115; t["d"] = 100
        return t
    }()

    static func parse(_ raw: String) -> Int? {
        let name = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if name.isEmpty { return nil }
        if let v = table[name] { return v }
        // "shift+a", "ctrl+f1"
        if name.contains("+") { return nil }
        if name.count == 1, let ch = name.unicodeScalars.first, ch.value < 128 {
            return Int(ch.value)
        }
        return nil
    }

    /// Splits "ctrl+shift+s" into modifier keys plus the base key.
    static func parseCombo(_ raw: String) -> [Int]? {
        let parts = raw.split(separator: "+").map { String($0) }
        guard !parts.isEmpty else { return nil }
        var out: [Int] = []
        for p in parts {
            guard let k = parse(p) else { return nil }
            out.append(k)
        }
        return out
    }

    static let names: [String] = table.keys.sorted()

    /// macOS virtual keycode -> RETROK.
    static func fromMacKeyCode(_ code: UInt16, characters: String?) -> Int? {
        switch code {
        case 126: return 273  // up
        case 125: return 274  // down
        case 124: return 275  // right
        case 123: return 276  // left
        case 36:  return 13   // return
        case 76:  return 271  // keypad enter
        case 48:  return 9    // tab
        case 49:  return 32   // space
        case 51:  return 8    // backspace
        case 53:  return 27   // esc
        case 117: return 127  // delete
        case 115: return 278  // home
        case 119: return 279  // end
        case 116: return 280  // pageup
        case 121: return 281  // pagedown
        // numpad, so a physical keypad drives the game the way the manual says
        case 82:  return 256  // kp0
        case 83:  return 257  // kp1
        case 84:  return 258
        case 85:  return 259
        case 86:  return 260
        case 87:  return 261
        case 88:  return 262
        case 89:  return 263
        case 91:  return 264
        case 92:  return 265  // kp9
        case 122: return 282  // f1
        case 120: return 283
        case 99:  return 284
        case 118: return 285
        case 96:  return 286
        case 97:  return 287
        case 98:  return 288
        case 100: return 289
        case 101: return 290
        case 109: return 291
        case 103: return 292
        case 111: return 293
        default: break
        }
        if let ch = characters?.lowercased().unicodeScalars.first, ch.value >= 32, ch.value < 127 {
            return Int(ch.value)
        }
        return nil
    }
}

struct ActionRecord {
    let time: Date
    let verb: String
    let target: String
    let payload: String
    let ok: Bool
}

final class ActionLog {
    private let lock = NSLock()
    private var storage: [ActionRecord] = []
    var onChange: (() -> Void)?
    private let limit = 500

    var items: [ActionRecord] {
        lock.lock(); defer { lock.unlock() }
        return storage
    }

    func add(_ verb: String, _ target: String, payload: String = "", ok: Bool = true) {
        lock.lock()
        storage.append(ActionRecord(time: Date(), verb: verb, target: target, payload: payload, ok: ok))
        if storage.count > limit { storage.removeFirst(storage.count - limit) }
        lock.unlock()
        DispatchQueue.main.async { self.onChange?() }
    }
}

extension RetroKey {
    static func label(for code: Int) -> String {
        if let (name, _) = table.first(where: { $0.value == code && $0.key.count > 1 }) { return name }
        if let s = Unicode.Scalar(UInt32(code)), code >= 32, code < 127 { return String(Character(s)) }
        return "key:\(code)"
    }
}
