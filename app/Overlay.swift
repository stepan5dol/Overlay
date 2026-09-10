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
    @Published var results: [String] = []
    @Published var chapter: Int = 0
    @Published var chapters: Int = 0
    @Published var assembling = false
    @Published var stats: [String: Double] = [:]
    @Published var resumed = false
    @Published var startedAt: Date? = nil

    /// Оценка по уже сделанному: сколько ушло на n фрагментов, столько же
    /// в среднем уйдёт на оставшиеся. Врёт на первых, поэтому до пяти молчим.
    var remaining: String? {
        guard let s = startedAt, done >= 5, total > done else { return nil }
        let per = Date().timeIntervalSince(s) / Double(done)
        let left = per * Double(total - done)
        let m = Int(left) / 60, sec = Int(left) % 60
        return m > 0 ? "≈ \(m) мин \(sec) с" : "≈ \(sec) с"
    }

    private var task: Process?
    private var stopped = false
    private var lastStage = "синтез"
    @Published var failure: String? = nil

    @Published var voices: [String] = []
    @Published var presets: [String] = []
    /// Системные голоса: (значение для --voice, что показать человеку)
    @Published var system: [(String, String)] = []
    @Published var fast: [(String, String)] = []

    /// Список голосов берётся у самого конвейера, чтобы не расходился с refs/.
    func loadVoices() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [repoRoot + "/src/book.py", "--list-voices"]
        let pipe = Pipe(); p.standardOutput = pipe
        do { try p.run() } catch { return }
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(),
                         encoding: .utf8) ?? ""
        p.waitUntilExit()
        for line in out.split(separator: "\n") {
            let parts = line.split(separator: ":", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let names = parts[1].split(separator: ",").map {
                $0.trimmingCharacters(in: .whitespaces) }
            if line.hasPrefix("референсы") { voices = names }
            if line.hasPrefix("пресеты") { presets = names }
            let pairs: ([String]) -> [(String, String)] = { ns in
                ns.map { n in
                    let p = n.split(separator: "|", maxSplits: 1)
                    return (String(p[0]), p.count > 1 ? String(p[1]) : String(p[0]))
                }
            }
            if line.hasPrefix("система") { system = pairs(names) }
            if line.hasPrefix("быстрые") { fast = pairs(names) }
        }
    }

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

    var python: String {
        (Bundle.main.object(forInfoDictionaryKey: "ThoriumPython") as? String)
            ?? UserDefaults.standard.string(forKey: "python")
            ?? "/usr/bin/python3"
    }

    func run(book: String, language: String, voice: String, speed: Double,
             format: String, dest: String) {
        guard !running else { return }
        stopped = false; failure = nil
        running = true; done = 0; total = 0; result = nil; results = []
        chapter = 0; chapters = 0; startedAt = Date()
        assembling = false; stats = [:]; resumed = false
        log = ""; stage = "Разбор книги…"

        let root = repoRoot
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        var argv = [root + "/src/book.py", book]
        if language != "auto" { argv += ["--language", language] }
        if !voice.isEmpty { argv += ["--voice", voice] }
        if abs(speed - 1.0) > 0.001 { argv += ["--speed", String(format: "%.2f", speed)] }
        argv += ["--format", format]
        if !dest.isEmpty { argv += ["--dest", dest] }
        p.arguments = argv
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
                guard let self else { return }
                self.running = false
                if proc.terminationStatus == 0 && !self.results.isEmpty {
                    self.stage = "Готово"
                } else if self.stopped {
                    self.stage = "Остановлено. Работа сохранена — перетащите книгу снова, чтобы продолжить"
                } else if let f = self.failure {
                    self.stage = f
                } else {
                    self.stage = "Прервалось на этапе «\(self.lastStage)». Работа сохранена — перетащите книгу снова"
                }
            }
        }
        task = p
        do { try p.run() } catch {
            running = false; stage = "Не удалось запустить: \(error.localizedDescription)"
        }
    }

    /// Останавливает весь свой прогон -- посредника и рабочие процессы
    /// синтеза, -- не задевая другие запущенные прогоны.
    func stop() {
        guard let p = task, p.isRunning else { running = false; return }
        let gid = getpgid(p.processIdentifier)
        if gid > 0 { killpg(gid, SIGTERM) } else { p.terminate() }
        stopped = true
        running = false
        stage = "Остановлено"
    }

    private func absorb(_ chunk: String) {
        for raw in chunk.replacingOccurrences(of: "\r", with: "\n").split(
            separator: "\n", omittingEmptySubsequences: true) {
            let line = String(raw)
            // Полосу двигает только счётчик tqdm вида "17/218 [". Строка
            // "к синтезу: 0 (готово: 218)" тоже содержит числа, и без этой
            // проверки прогресс скакал на 100% в самом начале.
            if let m = line.range(of: #"(\d+)/(\d+) \["#, options: .regularExpression) {
                let nums = line[m].dropLast(2).split(separator: "/")
                if nums.count == 2, let d = Int(nums[0]), let t = Int(nums[1]), t > 0 {
                    done = d; total = t
                    stage = chapters > 1
                        ? "Глава \(chapter) из \(chapters) · фрагмент \(d) из \(t)"
                        : "Фрагмент \(d) из \(t)"
                }
            }
            if line.hasPrefix("ПРОДОЛЖАЮ ") { resumed = true }
            if line.hasPrefix("СБОЙ ") { failure = String(line.dropFirst(5)) }
            if line.hasPrefix("ЭТАП ") {
                assembling = true
                let t = String(line.dropFirst(5))
                stage = t.prefix(1).uppercased() + t.dropFirst()
                lastStage = t
            }
            if line.hasPrefix("СТАТИСТИКА ") {
                let json = String(line.dropFirst("СТАТИСТИКА ".count))
                if let d = json.data(using: .utf8),
                   let o = try? JSONSerialization.jsonObject(with: d)
                            as? [String: Any] {
                    var m: [String: Double] = [:]
                    for (k, v) in o { m[k] = (v as? NSNumber)?.doubleValue ?? 0 }
                    stats = m
                }
            }
            if line.hasPrefix("ГЛАВЫ ") {
                chapters = Int(line.dropFirst(6).trimmingCharacters(in: .whitespaces)) ?? 0
            }
            if line.hasPrefix("ГЛАВА ") {
                let rest = line.dropFirst(6)
                chapter = Int(rest.prefix(while: { $0.isNumber })) ?? chapter
            }
            if line.hasPrefix("готово: ") {
                let path = String(line.dropFirst("готово: ".count))
                results.append(path)
                result = path
            }
            if line.hasPrefix("язык:") || line.hasPrefix("голос:") || line.hasPrefix("книга:") {
                stage = line
            }
            log += line + "\n"
            if log.count > 20000 { log = String(log.suffix(16000)) }
        }
    }
}


// MARK: - Оформление

private struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(.background.secondary))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(.separator.opacity(0.6), lineWidth: 0.5))
    }
}

struct DropZone: View {
    let onPick: (String) -> Void
    @State private var hovering = false

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "text.book.closed")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(hovering ? AnyShapeStyle(Color.accentColor)
                                          : AnyShapeStyle(.tertiary))
                .symbolEffect(.bounce, value: hovering)
            VStack(spacing: 3) {
                Text("Перетащите книгу").font(.title3.weight(.medium))
                Text("EPUB").font(.caption).foregroundStyle(.tertiary)
            }
            Button("Выбрать файл…") { pick() }
                .buttonStyle(.glass)
                .controlSize(.large)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .background(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .fill(hovering ? AnyShapeStyle(Color.accentColor.opacity(0.08))
                           : AnyShapeStyle(.background.secondary)))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .strokeBorder(hovering ? AnyShapeStyle(Color.accentColor)
                                   : AnyShapeStyle(.separator),
                          style: StrokeStyle(lineWidth: hovering ? 2 : 1,
                                             dash: hovering ? [] : [6, 5])))
        .animation(.smooth(duration: 0.18), value: hovering)
        .onDrop(of: [.fileURL], isTargeted: $hovering) { providers in
            guard let p = providers.first else { return false }
            _ = p.loadObject(ofClass: URL.self) { url, _ in
                guard let url, url.pathExtension.lowercased() == "epub" else { return }
                DispatchQueue.main.async { onPick(url.path) }
            }
            return true
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "epub") ?? .data]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { onPick(url.path) }
    }
}

struct ContentView: View {
    @StateObject private var runner = Runner()
    @AppStorage("language") private var language = "auto"
    @AppStorage("voice") private var voice = ""
    @AppStorage("speed") private var speed = 1.0
    @AppStorage("format") private var format = "epub"
    @AppStorage("dest") private var dest = ""

    private var destPath: String {
        dest.isEmpty ? NSHomeDirectory() + "/Documents" : dest
    }
    @State private var showLog = false

    /// Панель «Устный контент» в Системных настройках: оттуда качаются
    /// улучшенные голоса. Программно скачать их нельзя -- API не существует.
    private func openVoiceSettings() {
        let urls = [
            "x-apple.systempreferences:com.apple.Accessibility-Settings.extension?SpokenContent",
            "x-apple.systempreferences:com.apple.Accessibility-Settings.extension",
            "x-apple.systempreferences:com.apple.preference.universalaccess",
        ]
        for u in urls where NSWorkspace.shared.open(URL(string: u)!) { return }
    }

    private func start(_ path: String) {
        runner.run(book: path, language: language, voice: voice, speed: speed,
                   format: format, dest: destPath)
    }

    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.directoryURL = URL(fileURLWithPath: destPath)
        if panel.runModal() == .OK, let u = panel.url { dest = u.path }
    }

    // MARK: настройки

    private var settingsCard: some View {
        Card {
            VStack(spacing: 14) {
                row("Язык") {
                    Picker("", selection: $language) {
                        Text("Определить по книге").tag("auto")
                        Text("Русский").tag("ru")
                        Text("English").tag("en")
                    }.labelsHidden().pickerStyle(.menu)
                }
                Divider().opacity(0.5)
                row("Голос") {
                    Picker("", selection: $voice) {
                        Text("По языку книги").tag("")
                        if !runner.voices.isEmpty {
                            Section("Клонирование по образцу") {
                                ForEach(runner.voices, id: \.self) { Text($0).tag($0) }
                            }
                        }
                        if !runner.presets.isEmpty {
                            Section("Готовые голоса") {
                                ForEach(runner.presets, id: \.self) { Text($0).tag($0) }
                            }
                        }
                        if !runner.fast.isEmpty {
                            Section("Быстрые — Kokoro") {
                                ForEach(runner.fast, id: \.0) { v in
                                    Text(v.1).tag(v.0)
                                }
                            }
                        }
                        if !runner.system.isEmpty {
                            Section("Системные — подсветка по словам") {
                                ForEach(runner.system, id: \.0) { v in
                                    Text(v.1).tag(v.0)
                                }
                            }
                        }
                    }.labelsHidden().pickerStyle(.menu)
                }
                HStack(spacing: 6) {
                    Image(systemName: "waveform.badge.plus").foregroundStyle(.secondary)
                    Text("Системные голоса высокого качества")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("скачать в настройках") { openVoiceSettings() }
                        .buttonStyle(.link).font(.caption)
                    Spacer()
                }
                if voice.hasPrefix("apple:") && voice.contains(".compact.") {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                        Text("Выбран голос базового качества. Улучшенные Apple не "
                             + "разрешает скачивать из приложений — только вручную, "
                             + "в разделе «Устный контент». Голоса Siri сторонним "
                             + "приложениям недоступны вовсе.")
                            .font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.orange.opacity(0.10)))
                }
                Divider().opacity(0.5)
                row("Результат") {
                    Picker("", selection: $format) {
                        Text("Книга с подсветкой").tag("epub")
                        Text("Аудиокнига M4B").tag("m4b")
                        Text("И то, и другое").tag("both")
                    }.labelsHidden().pickerStyle(.menu)
                }
                Divider().opacity(0.5)
                row("Папка") {
                    HStack(spacing: 8) {
                        Text((destPath as NSString).abbreviatingWithTildeInPath)
                            .font(.callout).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                        Button("Изменить…") { pickFolder() }
                            .buttonStyle(.link).font(.callout)
                        Spacer()
                    }
                }
                Divider().opacity(0.5)
                row("Темп") {
                    HStack(spacing: 10) {
                        Slider(value: $speed, in: 0.7...1.6, step: 0.05)
                        Text(String(format: "%.2f×", speed))
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .frame(width: 48, alignment: .trailing)
                    }
                }
            }
        }
        .disabled(runner.running)
    }

    private func row<C: View>(_ label: String, @ViewBuilder _ control: () -> C) -> some View {
        HStack {
            Text(label).font(.callout).foregroundStyle(.secondary)
                .frame(width: 62, alignment: .leading)
            control()
        }
    }

    // MARK: ход работы

    private var progressCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text(runner.assembling ? "Сборка"
                         : (runner.total > 0
                            ? "\(Int(Double(runner.done) / Double(runner.total) * 100))%"
                            : "…"))
                        .font(.system(size: 30, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                        .contentTransition(.numericText())
                    Spacer()
                    if let r = runner.remaining {
                        Text(r).font(.callout).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
                if runner.assembling {
                    ProgressView().progressViewStyle(.linear)
                } else {
                    ProgressView(value: Double(runner.done),
                                 total: Double(max(runner.total, 1)))
                        .progressViewStyle(.linear)
                }
                if runner.resumed {
                    HStack(spacing: 6) {
                        Image(systemName: "arrow.clockwise")
                            .foregroundStyle(.secondary)
                        Text("Продолжаю прерванную работу — озвученное не переделывается")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                if runner.chapters > 1 && !runner.assembling {
                    HStack(spacing: 6) {
                        Image(systemName: "book.pages").foregroundStyle(.tertiary)
                        Text("Глава \(runner.chapter) из \(runner.chapters)")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
                Text(runner.stage)
                    .font(.callout).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle)
            }
        }
    }

    /// Итог одной строкой: длительность, объём текста, размер файлов.
    private var statLine: String {
        let s = runner.stats
        var parts: [String] = []
        if let sec = s["секунды"], sec > 0 {
            let h = Int(sec) / 3600, m = (Int(sec) % 3600) / 60
            let ss = Int(sec) % 60
            if h > 0 { parts.append("\(h) ч \(m) мин") }
            else if m > 0 { parts.append("\(m) мин \(ss) с") }
            else { parts.append("\(ss) с") }
        }
        if let w = s["слова"], w > 0 {
            parts.append("\(Int(w)) слов")
        }
        if let ch = s["главы"], ch > 1 {
            parts.append("\(Int(ch)) глав")
        }
        if let b = s["байты"], b > 0 {
            parts.append(ByteCountFormatter.string(fromByteCount: Int64(b),
                                                   countStyle: .file))
        }
        return parts.joined(separator: " · ")
    }

    private var resultCard: some View {
        Card {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(.white, Color.accentColor)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Книга озвучена").font(.headline)
                    if !runner.stats.isEmpty {
                        Text(statLine).font(.callout).foregroundStyle(.secondary)
                    }
                    ForEach(runner.results, id: \.self) { r in
                        Text(URL(fileURLWithPath: r).lastPathComponent)
                            .font(.caption).foregroundStyle(.tertiary)
                            .lineLimit(1).truncationMode(.middle)
                    }
                }
                Spacer()
                Button("Показать") {
                    let urls = runner.results.map { URL(fileURLWithPath: $0) }
                    if !urls.isEmpty {
                        NSWorkspace.shared.activateFileViewerSelecting(urls)
                    }
                }.buttonStyle(.glassProminent)
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Overlay").font(.largeTitle.weight(.semibold))
                Text("Книга становится книгой с озвучкой: текст подсвечивается по ходу чтения")
                    .font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if runner.running {
                progressCard
            } else if runner.result != nil {
                resultCard
            } else {
                DropZone(onPick: start)
                settingsCard
            }

            HStack(spacing: 12) {
                Button(showLog ? "Скрыть подробности" : "Подробности") {
                    withAnimation(.smooth(duration: 0.2)) { showLog.toggle() }
                }
                .buttonStyle(.link).font(.callout)
                Spacer()
                if runner.running {
                    Button("Остановить", role: .destructive) { runner.stop() }
                        .buttonStyle(.glass)
                } else if runner.result != nil {
                    Button("Ещё книгу") {
                        runner.result = nil
                        runner.stage = "Перетащите книгу в окно"
                    }.buttonStyle(.glass)
                }
            }

            if showLog {
                ScrollView {
                    Text(runner.log.isEmpty ? "пока пусто" : runner.log)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(10)
                }
                .frame(height: 150)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(.black.opacity(0.06)))
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(24)
        .frame(width: 520)
        .background(.background)
        .animation(.smooth(duration: 0.25), value: runner.running)
        .animation(.smooth(duration: 0.25), value: runner.result)
        .task { runner.loadVoices() }
    }
}

@main
struct OverlayApp: App {
    var body: some Scene {
        Window("Overlay", id: "main") { ContentView() }
            .windowResizability(.contentSize)
            .windowStyle(.hiddenTitleBar)
    }
}
