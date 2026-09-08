import AVFoundation
import Foundation

// Синтез системным голосом Apple. Отличие от нейросетевого движка в том, что
// здесь известны границы каждого произносимого слова: их отдаёт делегат
// одновременно с аудио, поэтому подсветку можно вести по словам, а не по
// предложениям, и никакого выравнивания не требуется.
//
// Протокол: на вход строки JSON {"id": "...", "text": "..."}, на выход
// строки JSON {"id": ..., "seconds": ..., "words": [{"begin","end","text"}]}.

struct Task: Decodable { let id: String; let text: String }

final class Speaker: NSObject, AVSpeechSynthesizerDelegate {
    // Синтезатор создаётся заново на каждый фрагмент: повторный write() на том
    // же объекте молча отдаёт пустой результат.
    var synth = AVSpeechSynthesizer()
    var frames: AVAudioFramePosition = 0
    var rate: Double = 0
    var words: [[String: Any]] = []
    var pending: (loc: Int, len: Int, text: String, begin: Double)? = nil
    var finished = false

    override init() {
        super.init()
        synth.delegate = self
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer,
                           willSpeakRangeOfSpeechString r: NSRange,
                           utterance u: AVSpeechUtterance) {
        let now = rate > 0 ? Double(frames) / rate : 0
        if let p = pending {
            words.append(["begin": p.begin, "end": now, "text": p.text,
                          "loc": p.loc, "len": p.len])
        }
        let w = (u.speechString as NSString).substring(with: r)
        pending = (r.location, r.length, w, now)
    }

    func render(text: String, voice: AVSpeechSynthesisVoice?, rate speechRate: Float,
                to url: URL) throws -> Double {
        frames = 0; words = []; pending = nil; finished = false
        synth = AVSpeechSynthesizer()
        synth.delegate = self
        let u = AVSpeechUtterance(string: text)
        u.voice = voice
        u.rate = speechRate

        var file: AVAudioFile? = nil
        synth.write(u) { [weak self] buf in
            guard let self, let pcm = buf as? AVAudioPCMBuffer else { return }
            if pcm.frameLength == 0 { self.finished = true; return }
            if file == nil {
                self.rate = pcm.format.sampleRate
                file = try? AVAudioFile(forWriting: url,
                                        settings: pcm.format.settings,
                                        commonFormat: pcm.format.commonFormat,
                                        interleaved: pcm.format.isInterleaved)
            }
            try? file?.write(from: pcm)
            self.frames += AVAudioFramePosition(pcm.frameLength)
        }
        let deadline = Date().addingTimeInterval(120)
        while !finished && Date() < deadline {
            RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.02))
        }
        let total = rate > 0 ? Double(frames) / rate : 0
        if let p = pending {                       // последнее слово закрываем концом
            words.append(["begin": p.begin, "end": total, "text": p.text,
                          "loc": p.loc, "len": p.len])
        }
        return total
    }
}

func listVoices() {
    let quality: [AVSpeechSynthesisVoiceQuality: String] =
        [.default: "compact", .enhanced: "enhanced", .premium: "premium"]
    var out: [[String: Any]] = []
    for v in AVSpeechSynthesisVoice.speechVoices() {
        out.append(["identifier": v.identifier, "name": v.name,
                    "language": v.language, "quality": quality[v.quality] ?? "?"])
    }
    let d = try! JSONSerialization.data(withJSONObject: out)
    print(String(data: d, encoding: .utf8)!)
}

// разбор аргументов
var args = Array(CommandLine.arguments.dropFirst())
func option(_ name: String) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}
if args.contains("--list") { listVoices(); exit(0) }

guard let outDir = option("--out") else {
    FileHandle.standardError.write("нужен --out КАТАЛОГ или --list\n".data(using: .utf8)!)
    exit(2)
}
let voiceId = option("--voice")
let voice = voiceId.flatMap { AVSpeechSynthesisVoice(identifier: $0) }
if voiceId != nil && voice == nil {
    FileHandle.standardError.write(
        "голос \(voiceId!) не установлен; скачайте его в настройках системы\n"
            .data(using: .utf8)!)
    exit(3)
}
let speechRate = Float(option("--rate") ?? "") ?? AVSpeechUtteranceDefaultSpeechRate

let dec = JSONDecoder()
while let line = readLine(strippingNewline: true) {
    guard !line.isEmpty, let data = line.data(using: .utf8),
          let task = try? dec.decode(Task.self, from: data) else { continue }
    let url = URL(fileURLWithPath: outDir).appendingPathComponent(task.id + ".wav")
    // Свой объект на каждый фрагмент: запоздалый вызов от предыдущего
    // синтезатора иначе гасит следующий, и тот выходит пустым.
    let speaker = Speaker()
    do {
        let seconds = try speaker.render(text: task.text, voice: voice,
                                         rate: speechRate, to: url)
        let payload: [String: Any] = ["id": task.id, "seconds": seconds,
                                      "words": speaker.words]
        let d = try JSONSerialization.data(withJSONObject: payload)
        print(String(data: d, encoding: .utf8)!)
    } catch {
        let d = try! JSONSerialization.data(
            withJSONObject: ["id": task.id, "error": "\(error)"])
        print(String(data: d, encoding: .utf8)!)
    }
    fflush(stdout)
}
