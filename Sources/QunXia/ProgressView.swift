import AppKit

/// The game's own progress, beside the log, so a person watching a run can read
/// what the agent has actually achieved rather than how busy it looks.
///
/// These numbers come out of the machine image (`GameState`), never out of the
/// Control API, and the agent has no call that returns them.
final class ProgressView: NSView {
    private let titleLabel = NSTextField(labelWithString: "Progress")
    private let sourceLabel = NSTextField(labelWithString: "from the game's own state")
    private let grid = NSGridView(numberOfColumns: 4, rows: 0)
    private let reader = GameState.Reader()
    private let saver: GameSave?
    private var cells: [String: NSTextField] = [:]
    private var roster = NSTextField(labelWithString: "")
    private var timer: Timer?

    /// Label, key, and how the value is drawn. Books lead: fourteen of them end
    /// the game, and that is the score the benchmark is for.
    private static let fields: [(String, String)] = [
        ("books", "books"), ("level", "level"),
        ("items", "items"), ("kinds", "kinds"),
        ("hp", "hp"), ("skills", "skills"),
        ("exp", "exp"), ("party", "party"),
    ]

    init(saver: GameSave? = nil) {
        self.saver = saver
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = NSColor(calibratedWhite: 0.07, alpha: 1).cgColor

        titleLabel.font = .systemFont(ofSize: 12, weight: .semibold)
        titleLabel.textColor = NSColor(calibratedWhite: 0.85, alpha: 1)
        sourceLabel.font = .systemFont(ofSize: 10, weight: .regular)
        sourceLabel.textColor = NSColor(calibratedWhite: 0.45, alpha: 1)

        grid.rowSpacing = 3
        grid.columnSpacing = 8
        for row in stride(from: 0, to: Self.fields.count, by: 2) {
            var views: [NSView] = []
            for (label, key) in Self.fields[row..<min(row + 2, Self.fields.count)] {
                let name = NSTextField(labelWithString: label)
                name.font = .systemFont(ofSize: 10)
                name.textColor = NSColor(calibratedWhite: 0.5, alpha: 1)
                let value = NSTextField(labelWithString: "-")
                value.font = .monospacedDigitSystemFont(ofSize: 11, weight: .medium)
                value.textColor = NSColor(calibratedWhite: 0.9, alpha: 1)
                cells[key] = value
                views.append(name)
                views.append(value)
            }
            grid.addRow(with: views)
        }
        grid.column(at: 0).width = 42
        grid.column(at: 2).width = 42

        roster.font = .systemFont(ofSize: 10)
        roster.textColor = NSColor(calibratedWhite: 0.5, alpha: 1)
        roster.lineBreakMode = .byTruncatingTail

        for v in [titleLabel, sourceLabel, grid, roster] as [NSView] {
            v.translatesAutoresizingMaskIntoConstraints = false
            addSubview(v)
        }
        NSLayoutConstraint.activate([
            titleLabel.topAnchor.constraint(equalTo: topAnchor, constant: 10),
            titleLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            sourceLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 2),
            sourceLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            grid.topAnchor.constraint(equalTo: sourceLabel.bottomAnchor, constant: 8),
            grid.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            grid.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -8),
            roster.topAnchor.constraint(equalTo: grid.bottomAnchor, constant: 5),
            roster.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            roster.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -8),
        ])
    }

    required init?(coder: NSCoder) { fatalError() }

    override var intrinsicContentSize: NSSize { NSSize(width: 340, height: 138) }

    /// One serialise a second. The core takes its own lock for it, so this is
    /// safe beside the emulation thread and cheap enough not to be felt.
    func start() {
        guard timer == nil else { return }
        let t = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in self?.refresh() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
        refresh()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    private func refresh() {
        guard let p = reader.read() else { return }
        set("books", "\(p.books.count)/14", won: p.books.count == 14)
        set("level", "\(p.level)")
        set("items", "\(p.items)")
        set("kinds", "\(p.itemsDistinct)")
        set("hp", "\(p.hp)/\(p.maxhp)")
        set("skills", "\(p.skills)")
        set("exp", "\(p.exp)")
        // The party is only true in a save the game itself wrote, so it
        // appears once the run has been caught on the world map.
        let party = saver?.party
        set("party", party.map { "\($0.members.count)" } ?? "-")
        roster.stringValue = (party?.members ?? []).map { "\($0.name) \($0.level)" }
            .joined(separator: "   ")
        roster.toolTip = saver?.why
    }

    private func set(_ key: String, _ text: String, won: Bool = false) {
        guard let cell = cells[key] else { return }
        cell.stringValue = text
        cell.textColor = won
            ? NSColor(calibratedRed: 0.45, green: 0.85, blue: 0.62, alpha: 1)
            : NSColor(calibratedWhite: 0.9, alpha: 1)
    }
}
