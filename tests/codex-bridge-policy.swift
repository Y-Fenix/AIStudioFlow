import Foundation

func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { fatalError(message) }
}

@main
struct PolicyTests {
static func main() throws {
let valid = URL(string: "studioflow-codex://handoff?origin=https%3A%2F%2Fstudio.example.com&ticket=Abcdef0123456789_-Abcdef0123456789")!
expect(CodexBridgePolicy.parse(valid) != nil, "accept HTTPS handoff with URL-safe ticket")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://handoff?origin=http%3A%2F%2F127.0.0.1%3A8766&ticket=Abcdef0123456789_-Abcdef0123456789")!) != nil, "accept loopback development origin")
expect(CodexBridgePolicy.parse(URL(string: "https://handoff?origin=https%3A%2F%2Fstudio.example.com&ticket=Abcdef0123456789_-Abcdef0123456789")!) == nil, "reject wrong custom scheme")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://other?origin=https%3A%2F%2Fstudio.example.com&ticket=Abcdef0123456789_-Abcdef0123456789")!) == nil, "reject wrong custom host")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://handoff?origin=http%3A%2F%2Fevil.example&ticket=Abcdef0123456789_-Abcdef0123456789")!) == nil, "reject non-loopback HTTP origin")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://handoff?origin=https%3A%2F%2Fuser%3Apass%40studio.example.com&ticket=Abcdef0123456789_-Abcdef0123456789")!) == nil, "reject credentials in origin")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://handoff?origin=https%3A%2F%2Fstudio.example.com%2Fpath&ticket=Abcdef0123456789_-Abcdef0123456789")!) == nil, "reject path in origin")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://handoff?origin=https%3A%2F%2Fstudio.example.com&ticket=too-short")!) == nil, "reject short ticket")
expect(CodexBridgePolicy.parse(URL(string: "studioflow-codex://handoff?origin=https%3A%2F%2Fstudio.example.com&ticket=Abcdef0123456789%2FAbcdef0123456789")!) == nil, "reject non URL-safe ticket")
var payload = CodexBridgePayload()
try payload.append(Data(#"{"prompt":"Skill 中文正文"}"#.utf8))
expect(tryPrompt(payload) == "Skill 中文正文", "preserve prompt text")
var oversized = CodexBridgePayload()
do {
    try oversized.append(Data(repeating: 32, count: 600_001))
    fatalError("reject oversized response before decoding")
} catch {}
expect(oversized.count == 0, "do not retain oversized chunk")
for body in [#"{"prompt":""}"#, #"{"prompt":123}"#, "not JSON",
             "{\"prompt\":\"" + String(repeating: "中", count: 166_667) + "\"}"] {
    var invalid = CodexBridgePayload()
    try invalid.append(Data(body.utf8))
    do {
        _ = try invalid.prompt()
        fatalError("reject malformed or oversized prompt")
    } catch {}
}
print("Codex bridge URL and payload policy checks passed")
}

static func tryPrompt(_ payload: CodexBridgePayload) -> String { (try? payload.prompt()) ?? "" }
}
