import Foundation

struct CodexBridgePayload {
    static let maxResponseBytes = 600_000
    static let maxPromptBytes = 500_000
    private var data = Data()
    var count: Int { data.count }

    mutating func append(_ chunk: Data) throws {
        guard chunk.count <= Self.maxResponseBytes - data.count else {
            throw BridgeError("交接响应超过 600 KB，已停止接收")
        }
        data.append(chunk)
    }

    func prompt() throws -> String {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let prompt = object["prompt"] as? String, !prompt.isEmpty,
              prompt.utf8.count <= Self.maxPromptBytes else {
            throw BridgeError("交接正文格式无效或超过 500 KB（UTF-8）")
        }
        return prompt
    }
}

struct BridgeError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

struct CodexBridgeHandoff {
    let origin: String
    let base: URL
    let ticket: String
}

enum CodexBridgePolicy {
    static func parse(_ url: URL) -> CodexBridgeHandoff? {
        guard url.scheme == "studioflow-codex", url.host == "handoff",
              url.user == nil, url.password == nil, url.port == nil,
              url.path.isEmpty, url.fragment == nil,
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let items = parts.queryItems, items.count == 2,
              items.filter({ $0.name == "origin" }).count == 1,
              items.filter({ $0.name == "ticket" }).count == 1,
              let origin = items.first(where: { $0.name == "origin" })?.value,
              let ticket = items.first(where: { $0.name == "ticket" })?.value,
              (32...128).contains(ticket.utf8.count),
              ticket.utf8.allSatisfy({ (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95 }),
              let base = URL(string: origin), allowed(base) else { return nil }
        return CodexBridgeHandoff(origin: origin, base: base, ticket: ticket)
    }

    static func allowed(_ url: URL) -> Bool {
        guard url.user == nil, url.password == nil, url.query == nil,
              url.fragment == nil, url.path.isEmpty || url.path == "/",
              let host = url.host, !host.isEmpty else { return false }
        if url.scheme == "https" { return true }
        return url.scheme == "http" && ["127.0.0.1", "localhost", "::1", "[::1]"].contains(host)
    }
}
