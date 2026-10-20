import AppKit
import Foundation

final class RedirectBlocker: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

@MainActor
final class Bridge: NSObject, NSApplicationDelegate {
    private var handoffInProgress = false

    private func recordPhase(_ phase: String) {
        // Operational diagnostics only: never persist the URL, ticket or prompt.
        UserDefaults.standard.set(phase, forKey: "handoffLastPhase")
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: "handoffPhaseAt")
    }

    static func codexApplicationURL() -> URL? {
        // Resolve the installed bundle rather than assuming the app's filename
        // or Accessibility process name is literally "Codex".
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.openai.codex")
    }

    func registerURLHandler() {
        // Install before entering AppKit's event loop. The first URL may be
        // delivered before either of the launch delegate notifications.
        NSAppleEventManager.shared().setEventHandler(self, andSelector: #selector(handleURL(_:withReplyEvent:)), forEventClass: AEEventClass(kInternetEventClass), andEventID: AEEventID(kAEGetURL))
        recordPhase("handler-ready")
    }

    func applicationWillFinishLaunching(_ notification: Notification) { recordPhase("will-finish-launching") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        recordPhase("did-finish-launching")
        if CommandLine.arguments.count > 1, let url = URL(string: CommandLine.arguments[1]),
           url.scheme == "studioflow-codex" { Task { await handle(url) } }
    }

    @objc func handleURL(_ event: NSAppleEventDescriptor, withReplyEvent reply: NSAppleEventDescriptor) {
        recordPhase("url-received")
        guard let raw = event.paramDescriptor(forKeyword: keyDirectObject)?.stringValue,
              let url = URL(string: raw) else { showError("交接地址无效"); return }
        Task { await handle(url) }
    }

    private func handle(_ url: URL) async {
        guard !handoffInProgress else { showError("已有交接正在处理，请完成后重试"); return }
        handoffInProgress = true
        defer { handoffInProgress = false }
        guard let handoff = CodexBridgePolicy.parse(url) else {
            showError("来源、协议或交接票据无效"); return
        }
        do {
            recordPhase("redeeming")
            guard let applicationURL = Self.codexApplicationURL() else {
                throw BridgeError("未找到 Codex 桌面应用，请先安装并打开一次后重试")
            }
            var request = URLRequest(url: handoff.base.appendingPathComponent("api/codex-handoff/redeem"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["ticket": handoff.ticket, "origin": handoff.origin])
            request.timeoutInterval = 20
            let blocker = RedirectBlocker()
            let session = URLSession(configuration: .ephemeral, delegate: blocker, delegateQueue: nil)
            defer { session.invalidateAndCancel() }
            let (bytes, response) = try await session.bytes(for: request)
            guard response.url == request.url,
                  response.mimeType == "application/json" else { throw BridgeError("交接服务来源或响应类型不匹配") }
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw BridgeError("票据兑换失败；可能已过期或已使用") }
            guard response.expectedContentLength <= CodexBridgePayload.maxResponseBytes else {
                throw BridgeError("交接响应超过 600 KB，已停止接收")
            }
            var payload = CodexBridgePayload()
            var chunk = Data()
            for try await byte in bytes {
                chunk.append(byte)
                if chunk.count == 8192 {
                    try payload.append(chunk)
                    chunk.removeAll(keepingCapacity: true)
                }
            }
            try payload.append(chunk)
            let prompt = try payload.prompt()
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(prompt, forType: .string)
            recordPhase("copied")
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = true
            let application = try await NSWorkspace.shared.openApplication(at: applicationURL, configuration: configuration)
            try await Task.sleep(for: .seconds(1.5))
            try await CodexComposer.paste(prompt, into: application)
            recordPhase("pasted")
            showMessage("Skill 已放入 Codex 输入框。请检查内容后自行按 Enter；本工具不会发送。")
        } catch {
            recordPhase("failed")
            showError("\(error.localizedDescription)\n若已兑换，内容仍在剪贴板，可在 Codex 手动粘贴。")
        }
    }

    private func showMessage(_ text: String) { dialog("StudioFlow Codex", text) }
    private func showError(_ text: String) { dialog("StudioFlow Codex 交接失败", text) }
    private func dialog(_ title: String, _ text: String) {
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = text; alert.addButton(withTitle: "好"); alert.runModal()
    }
}

@main
@MainActor
struct StudioFlowCodexBridge {
    static func main() {
        if CommandLine.arguments.contains("--diagnostics") {
            print("phase: \(UserDefaults.standard.string(forKey: "handoffLastPhase") ?? "none")")
            print("phase_at: \(UserDefaults.standard.double(forKey: "handoffPhaseAt"))")
            return
        }
        if CommandLine.arguments.contains("--check-target") {
            guard let url = Bridge.codexApplicationURL() else {
                print("FAIL: 未找到 bundle ID 为 com.openai.codex 的桌面应用")
                exit(1)
            }
            print("PASS: 已找到 Codex 应用：\(url.path)")
            return
        }
        if CommandLine.arguments.contains("--check-composer") {
            guard let application = NSWorkspace.shared.runningApplications.first(where: { $0.bundleIdentifier == "com.openai.codex" }) else {
                print("FAIL: Codex 尚未运行"); exit(1)
            }
            do {
                _ = try CodexComposer.findEmpty(in: application)
                print("PASS: 已找到唯一、可编辑且为空的 Codex 发送框；未聚焦、粘贴或发送")
            } catch { print("FAIL: \(error.localizedDescription)"); exit(1) }
            return
        }
        let app = NSApplication.shared
        let delegate = Bridge()
        app.delegate = delegate
        delegate.registerURLHandler()
        withExtendedLifetime(delegate) { app.run() }
    }
}
