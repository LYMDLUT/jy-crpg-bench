import AppKit

/// Live view of everything the agent API has done, so you can watch a run happen.
final class HistoryView: NSView {
    private let titleLabel = NSTextField(labelWithString: "Control API")
    private let portLabel = NSTextField(labelWithString: "")
    private let scroll = NSScrollView()
    private let text: NSTextView
    private let log: ActionLog
    private var dirty = false

    init(log: ActionLog, port: UInt16) {
        self.log = log
        text = NSTextView(frame: NSRect(x: 0, y: 0, width: 320, height: 100))
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = NSColor(calibratedWhite: 0.07, alpha: 1).cgColor

        titleLabel.font = .systemFont(ofSize: 12, weight: .semibold)
        titleLabel.textColor = NSColor(calibratedWhite: 0.85, alpha: 1)
        portLabel.font = .monospacedSystemFont(ofSize: 10, weight: .regular)
        portLabel.textColor = NSColor(calibratedRed: 0.55, green: 0.82, blue: 0.62, alpha: 1)
        portLabel.stringValue = "http://127.0.0.1:\(port)"

        text.minSize = NSSize(width: 0, height: 0)
        text.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        text.isVerticallyResizable = true
        text.isHorizontallyResizable = false
        text.autoresizingMask = [.width]
        text.textContainer?.widthTracksTextView = true
        text.textContainer?.containerSize = NSSize(width: 320, height: CGFloat.greatestFiniteMagnitude)
        text.isEditable = false
        text.isSelectable = true
        text.drawsBackground = true
        text.backgroundColor = NSColor(calibratedWhite: 0.09, alpha: 1)
        text.textContainerInset = NSSize(width: 8, height: 8)

        scroll.documentView = text
        scroll.hasVerticalScroller = true
        scroll.borderType = .noBorder
        scroll.drawsBackground = false
        scroll.autohidesScrollers = true

        for v in [titleLabel, portLabel, scroll] as [NSView] {
            v.translatesAutoresizingMaskIntoConstraints = false
            addSubview(v)
        }
        NSLayoutConstraint.activate([
            widthAnchor.constraint(greaterThanOrEqualToConstant: 240),
            titleLabel.topAnchor.constraint(equalTo: topAnchor, constant: 10),
            titleLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            portLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 2),
            portLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            scroll.topAnchor.constraint(equalTo: portLabel.bottomAnchor, constant: 8),
            scroll.leadingAnchor.constraint(equalTo: leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: trailingAnchor),
            scroll.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])

        // Coalesce: a /keys burst can log dozens of lines in one frame.
        log.onChange = { [weak self] in
            guard let self, !self.dirty else { return }
            self.dirty = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                self.dirty = false
                self.reload()
            }
        }
        reload()
    }

    required init?(coder: NSCoder) { fatalError() }

    override var intrinsicContentSize: NSSize { NSSize(width: 320, height: NSView.noIntrinsicMetric) }

    func reload() {
        let attr = NSMutableAttributedString()
        for rec in log.items.suffix(200) {
            attr.append(line(rec))
            attr.append(NSAttributedString(string: "\n"))
            if let data = rec.image, let shot = NSImage(data: data) {
                attr.append(thumbnail(shot))
                attr.append(NSAttributedString(string: "\n"))
            }
        }
        text.textStorage?.setAttributedString(attr)
        text.scrollToEndOfDocument(nil)
    }

    /// Inline picture of the screen a call returned, indented under its line.
    private func thumbnail(_ image: NSImage) -> NSAttributedString {
        let width: CGFloat = 150
        let height = (image.size.height / max(1, image.size.width)) * width
        let cell = NSTextAttachmentCell(imageCell: image)
        let attachment = NSTextAttachment()
        attachment.attachmentCell = cell
        cell.image?.size = NSSize(width: width, height: height)
        let out = NSMutableAttributedString(string: "    ")
        out.append(NSAttributedString(attachment: attachment))
        return out
    }

    /// Renders key names as boxed glyphs, so a movement key reads as the screen
    /// direction it produces.
    private func keyChips(_ target: String) -> NSAttributedString {
        let out = NSMutableAttributedString()
        // KEYS logs a comma separated list, KEY a space separated one
        let tokens = target.split(whereSeparator: { $0 == " " || $0 == "," }).map(String.init)
        for token in tokens {
            if token.hasPrefix("x"), Int(token.dropFirst()) != nil {
                out.append(NSAttributedString(string: " " + token, attributes: [
                    .font: NSFont.monospacedSystemFont(ofSize: 10.5, weight: .regular),
                    .foregroundColor: NSColor(calibratedWhite: 0.45, alpha: 1),
                ]))
                continue
            }
            let isArrow = RetroKey.arrowNames.contains(token.lowercased())
            out.append(NSAttributedString(string: " " + RetroKey.glyph(token) + " ", attributes: [
                .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .medium),
                .foregroundColor: isArrow
                    ? NSColor(calibratedRed: 0.56, green: 0.80, blue: 0.97, alpha: 1)
                    : NSColor(calibratedWhite: 0.86, alpha: 1),
                .backgroundColor: NSColor(calibratedWhite: 0.16, alpha: 1),
            ]))
            out.append(NSAttributedString(string: " ", attributes: [
                .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
            ]))
        }
        return out
    }

    private static let clock: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private func line(_ rec: ActionRecord) -> NSAttributedString {
        let out = NSMutableAttributedString()
        func add(_ s: String, _ color: NSColor, bold: Bool = false) {
            out.append(NSAttributedString(string: s, attributes: [
                .font: NSFont.monospacedSystemFont(ofSize: 10.5, weight: bold ? .bold : .regular),
                .foregroundColor: color,
            ]))
        }
        add(Self.clock.string(from: rec.time) + " ", NSColor(calibratedWhite: 0.42, alpha: 1))
        let verbColor: NSColor
        switch rec.verb {
        case "KEY", "KEYS", "TEXT": verbColor = NSColor(calibratedRed: 0.45, green: 0.78, blue: 1.0, alpha: 1)
        case "SAVE": verbColor = NSColor(calibratedRed: 1.0, green: 0.72, blue: 0.32, alpha: 1)
        case "LOAD": verbColor = NSColor(calibratedRed: 1.0, green: 0.55, blue: 0.28, alpha: 1)
        case "RESET": verbColor = NSColor(calibratedRed: 1.0, green: 0.42, blue: 0.45, alpha: 1)
        case "GET": verbColor = NSColor(calibratedRed: 0.62, green: 0.82, blue: 0.55, alpha: 1)
        case "WAIT", "MOUSE": verbColor = NSColor(calibratedWhite: 0.6, alpha: 1)
        default: verbColor = NSColor(calibratedRed: 0.85, green: 0.75, blue: 1.0, alpha: 1)
        }
        add(rec.verb.padding(toLength: 5, withPad: " ", startingAt: 0), verbColor, bold: true)
        add(" ", NSColor.white)
        if rec.verb == "KEY" || rec.verb == "KEYS" {
            out.append(keyChips(rec.target))
        } else {
            add(rec.target, NSColor(calibratedWhite: 0.9, alpha: 1))
        }
        if !rec.payload.isEmpty {
            add(" " + rec.payload, NSColor(calibratedRed: 0.95, green: 0.85, blue: 0.45, alpha: 1))
        }
        if !rec.ok { add("  ✕", NSColor(calibratedRed: 1.0, green: 0.4, blue: 0.4, alpha: 1)) }
        return out
    }
}
