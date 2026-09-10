import SwiftUI
import AppKit

// Окно настроек: движки и разборщики, их установка, и всё, что не нужно
// держать перед глазами на главном экране.

struct Движок: Identifiable, Decodable {
    var id: String { имя }
    let имя: String
    let название: String
    let описание: String
    let установлен: Bool
    let гб_на_диске: Double
    let гб_скачать: Double
    let клонирование: Bool
    let батч: Bool
    let языки: [String]
}

@MainActor
final class Хозяйство: ObservableObject {
    @Published var движки: [Движок] = []
    @Published var ставится: String? = nil
    @Published var шаг: String = ""

    var repoRoot: String {
        let внутри = Bundle.main.resourcePath ?? ""
        if FileManager.default.fileExists(atPath: внутри + "/src/engines/status.py") {
            return внутри
        }
        return (Bundle.main.object(forInfoDictionaryKey: "ThoriumRepoRoot") as? String)
            ?? Bundle.main.bundleURL.deletingLastPathComponent()
                .deletingLastPathComponent().path
    }
    /// Интерпретатор для служебных задач: список голосов, установка
    /// движков. До установки первого движка своего окружения ещё нет,
    /// поэтому берём системный -- ему хватает стандартной библиотеки.
    var python: String {
        if var p = Bundle.main.object(forInfoDictionaryKey: "ThoriumPython") as? String {
            p = p.replacingOccurrences(of: "@BUNDLE@",
                                       with: Bundle.main.resourcePath ?? "")
            if FileManager.default.isExecutableFile(atPath: p) { return p }
        }
        return "/usr/bin/python3"
    }

    func обновить() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [repoRoot + "/src/engines/status.py"]
        let pipe = Pipe(); p.standardOutput = pipe
        do { try p.run() } catch { return }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        if let список = try? JSONDecoder().decode([Движок].self, from: data) {
            движки = список
        }
    }

    func поставить(_ имя: String) {
        guard ставится == nil else { return }
        ставится = имя; шаг = "готовлю окружение…"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [repoRoot + "/src/engines/install.py", имя]
        let pipe = Pipe(); p.standardOutput = pipe; p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { h in
            let s = String(data: h.availableData, encoding: .utf8) ?? ""
            for line in s.split(separator: "\n") where line.hasPrefix("ШАГ ") {
                DispatchQueue.main.async { self.шаг = String(line.dropFirst(4)) }
            }
        }
        p.terminationHandler = { _ in
            DispatchQueue.main.async {
                self.ставится = nil; self.шаг = ""
                self.обновить()
            }
        }
        try? p.run()
    }
}

struct SettingsView: View {
    @StateObject private var хозяйство = Хозяйство()
    @AppStorage("batch") private var batch = 8
    @AppStorage("dest") private var dest = ""
    @AppStorage("speed") private var speed = 1.0

    private var destPath: String {
        dest.isEmpty ? NSHomeDirectory() + "/Documents" : dest
    }

    var body: some View {
        TabView {
            общие.tabItem { Label("Общие", systemImage: "gearshape") }
            движки.tabItem { Label("Движки", systemImage: "cpu") }
        }
        .frame(width: 560, height: 420)
        .task { хозяйство.обновить() }
    }

    private var общие: some View {
        Form {
            Section {
                HStack {
                    Text((destPath as NSString).abbreviatingWithTildeInPath)
                        .lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Button("Изменить…") { выбрать() }
                }
            } header: { Text("Куда сохранять готовые книги") }

            Section {
                Picker("", selection: $batch) {
                    Text("По одному").tag(1)
                    Text("8").tag(8)
                    Text("16").tag(16)
                    Text("32").tag(32)
                    Text("64").tag(64)
                }.labelsHidden().pickerStyle(.segmented)
                Text("Сколько фрагментов Qwen считает за раз. Больше — быстрее "
                     + "и больше памяти. На M4 Pro: 8 даёт около 7×, 32 — около 9×. "
                     + "На машинах помощнее имеет смысл поднять.")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } header: { Text("Размер пакета") }

            Section {
                HStack {
                    Slider(value: $speed, in: 0.7...1.6, step: 0.05)
                    Text(String(format: "%.2f×", speed))
                        .font(.callout.monospacedDigit()).frame(width: 52)
                }
            } header: { Text("Темп речи") }
        }
        .formStyle(.grouped)
        .padding(.top, 6)
    }

    private var движки: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(хозяйство.движки) { д in
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: д.установлен
                              ? "checkmark.circle.fill" : "arrow.down.circle")
                            .font(.system(size: 20))
                            .foregroundStyle(д.установлен ? AnyShapeStyle(Color.accentColor)
                                                          : AnyShapeStyle(.tertiary))
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 6) {
                                Text(д.название).font(.callout.weight(.medium))
                                if д.клонирование {
                                    Ярлык("клонирует голос")
                                }
                                if д.батч { Ярлык("пакетами") }
                            }
                            Text(д.описание).font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            Text(д.установлен
                                 ? String(format: "на диске %.1f ГБ", д.гб_на_диске)
                                 : String(format: "скачать около %.1f ГБ", д.гб_скачать))
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                        Spacer()
                        if хозяйство.ставится == д.имя {
                            VStack(alignment: .trailing, spacing: 3) {
                                ProgressView().controlSize(.small)
                                Text(хозяйство.шаг).font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }.frame(width: 150, alignment: .trailing)
                        } else if !д.установлен {
                            Button("Скачать") { хозяйство.поставить(д.имя) }
                                .buttonStyle(.glassProminent)
                                .disabled(хозяйство.ставится != nil)
                        }
                    }
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(.background.secondary))
                }
            }
            .padding(16)
        }
    }

    private func Ярлык(_ t: String) -> some View {
        Text(t).font(.caption2)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill(Color.accentColor.opacity(0.15)))
    }

    private func выбрать() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.directoryURL = URL(fileURLWithPath: destPath)
        if panel.runModal() == .OK, let u = panel.url { dest = u.path }
    }
}


/// Окно настроек, открываемое из главного окна.
///
/// Приложение собрано без строки меню, поэтому стандартный пункт
/// «Настройки…» отсутствует и селектор showSettingsWindow: ничего не даёт.
enum ОкноНастроек {
    private static var окно: NSWindow?

    @MainActor
    static func показать() {
        if let w = окно {
            w.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let w = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 420),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered, defer: false)
        w.title = "Настройки"
        w.isReleasedWhenClosed = false
        w.center()
        w.contentView = NSHostingView(rootView: SettingsView())
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        окно = w
    }
}
