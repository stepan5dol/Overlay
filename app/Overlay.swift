import SwiftUI
import UniformTypeIdentifiers
import AppKit

// Оболочка над src/book.py: книга на входе, EPUB с синхронной озвучкой на выходе.
// Вся работа делается конвейером, здесь только выбор файла, ход работы и результат.

final class Runner: ObservableObject {
    @Published var running = false
    @Published var done: Int = 0
    @Published var total: Int = 0
    @Published var stage: String = "Перетащите книгу в окно"
    @Published var log: String = ""
    @Published var result: String? = nil

    private var task: Process?

    // Путь к репозиторию прописывается при сборке, чтобы бандл можно было
    // положить в /Applications. Если ключа нет — ищем на два уровня вверх.
    private var repoRoot: String {
        if let p = Bundle.main.object(forInfoDictionaryKey: "ThoriumRepoRoot") as? String,
           FileManager.default.fileExists(atPath: p + "/src/book.py") {
            return p
        }
        return Bundle.main.bundleURL.deletingLastPathComponent()
            .deletingLastPathComponent().path
    }

    func run(book: String) {
        guard !running else { return }
        running = true; done = 0; total = 0; result = nil
        log = ""; stage = "Разбор книги…"

        let root = repoRoot
        let py = (Bundle.main.object(forInfoDictionaryKey: "ThoriumPython") as? String)
            ?? UserDefaults.standard.string(forKey: "python")
            ?? "/usr/bin/python3"

        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [root + "/src/book.py", book]
        p.currentDirectoryURL = URL(fileURLWithPath: root)

        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty, let s = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.absorb(s) }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                self?.running = false
                self?.stage = proc.terminationStatus == 0 ? "Готово" : "Прервано"
            }
        }
        task = p
        do { try p.run() } catch {
            running = false; stage = "Не удалось запустить: \(error.localizedDescription)"
        }
    }

    func stop() {
        task?.terminate()
        running = false
        stage = "Остановлено"
    }

    private func absorb(_ chunk: String) {
        for raw in chunk.replacingOccurrences(of: "\r", with: "\n").split(
            separator: "\n", omittingEmptySubsequences: true) {
            let line = String(raw)
            if let m = line.range(of: #"(\d+)/(\d+)"#, options: .regularExpression) {
                let parts = line[m].split(separator: "/")
                if parts.count == 2, let d = Int(parts[0]), let t = Int(parts[1]), t > 1 {
                    done = d; total = t
                    stage = "Озвучка: \(d) из \(t)"
                }
            }
            if line.hasPrefix("готово: ") {
                result = String(line.dropFirst("готово: ".count))
            }
            if line.hasPrefix("язык:") || line.hasPrefix("голос:") || line.hasPrefix("книга:") {
                stage = line
            }
            log += line + "\n"
            if log.count > 20000 { log = String(log.suffix(16000)) }
        }
    }
}

struct DropZone: View {
    @ObservedObject var runner: Runner
    @State private var hovering = false

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [7, 5]))
                .foregroundStyle(hovering ? Color.accentColor : Color.secondary.opacity(0.5))
            VStack(spacing: 8) {
                Image(systemName: "book.closed")
                    .font(.system(size: 34, weight: .light))
                Text("Перетащите .epub сюда")
                    .font(.callout)
                Button("Выбрать файл…") { pick() }
                    .buttonStyle(.link)
            }
            .foregroundStyle(.secondary)
        }
        .frame(height: 132)
        .onDrop(of: [.fileURL], isTargeted: $hovering) { providers in
            guard let p = providers.first else { return false }
            _ = p.loadObject(ofClass: URL.self) { url, _ in
                guard let url, url.pathExtension.lowercased() == "epub" else { return }
                DispatchQueue.main.async { runner.run(book: url.path) }
            }
            return true
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "epub") ?? .data]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            runner.run(book: url.path)
        }
    }
}

struct ContentView: View {
    @StateObject private var runner = Runner()

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Overlay").font(.title2).bold()
            Text("Книга → EPUB с синхронной озвучкой")
                .font(.caption).foregroundStyle(.secondary)

            if !runner.running && runner.result == nil {
                DropZone(runner: runner)
            }

            Text(runner.stage).font(.callout)

            if runner.total > 0 {
                ProgressView(value: Double(runner.done), total: Double(runner.total))
            } else if runner.running {
                ProgressView().progressViewStyle(.linear)
            }

            if let r = runner.result {
                HStack {
                    Text(URL(fileURLWithPath: r).lastPathComponent)
                        .font(.callout).lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Button("Показать в Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting(
                            [URL(fileURLWithPath: r)])
                    }
                }
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 8)
                    .fill(Color.secondary.opacity(0.12)))
            }

            DisclosureGroup("Журнал") {
                ScrollView {
                    Text(runner.log)
                        .font(.system(size: 11, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }.frame(height: 150)
            }

            HStack {
                Spacer()
                if runner.running {
                    Button("Остановить") { runner.stop() }
                } else if runner.result != nil {
                    Button("Ещё книгу") { runner.result = nil; runner.stage = "Перетащите книгу в окно" }
                }
            }
        }
        .padding(20)
        .frame(width: 520)
    }
}

@main
struct OverlayApp: App {
    var body: some Scene {
        Window("Overlay", id: "main") { ContentView() }
            .windowResizability(.contentSize)
    }
}
