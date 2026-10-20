import AppKit
import ApplicationServices

struct CodexComposerDescriptor {
    var role: String
    var classes: [String]
    var ancestorClasses: [[String]]
    var enabled: Bool
    var characters: Int?
    var placeholderOnly = false

    var isEmpty: Bool { characters == 0 || (characters != nil && placeholderOnly) }
}

enum CodexComposerPolicy {
    static func recognizes(_ element: CodexComposerDescriptor) -> Bool {
        element.role == "AXTextArea" && element.classes.contains("ProseMirror") &&
            element.ancestorClasses.joined().contains(where: { $0.hasPrefix("_ComposerLayoutBody_") })
    }

    static func select(_ elements: [CodexComposerDescriptor]) -> Int? {
        let matches = elements.indices.filter { recognizes(elements[$0]) }
        guard matches.count == 1, let index = matches.first,
              elements[index].enabled, elements[index].isEmpty else { return nil }
        return index
    }

    static func verifies(_ prompt: String, pasted: String) -> Bool { prompt == pasted }
}

@MainActor
enum CodexComposer {
    private static func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
        return value
    }

    private static func uiElement(_ value: CFTypeRef?) -> AXUIElement? {
        guard let value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(value, to: AXUIElement.self)
    }

    private static func describe(_ element: AXUIElement) -> CodexComposerDescriptor {
        var ancestors: [[String]] = []
        var current = element
        for _ in 0..<4 {
            guard let parent = uiElement(attribute(current, kAXParentAttribute)) else { break }
            ancestors.append(attribute(parent, "AXDOMClassList") as? [String] ?? [])
            current = parent
        }
        let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
        let placeholderOnly = children.count == 1 &&
            (attribute(children[0], "AXDOMClassList") as? [String] ?? []).contains("placeholder")
        return CodexComposerDescriptor(
            role: attribute(element, kAXRoleAttribute) as? String ?? "",
            classes: attribute(element, "AXDOMClassList") as? [String] ?? [],
            ancestorClasses: ancestors,
            enabled: attribute(element, kAXEnabledAttribute) as? Bool ?? false,
            characters: attribute(element, kAXNumberOfCharactersAttribute) as? Int,
            placeholderOnly: placeholderOnly)
    }

    static func findEmpty(in application: NSRunningApplication) throws -> AXUIElement {
        guard AXIsProcessTrusted() else {
            throw BridgeError("请在系统设置的隐私与安全性→辅助功能中允许 StudioFlow Codex Bridge，然后重试；也可手动粘贴")
        }
        let root = AXUIElementCreateApplication(application.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 1)
        var queue: [(AXUIElement, Int)] = [(root, 0)]
        var cursor = 0
        var candidates: [AXUIElement] = []
        var descriptors: [CodexComposerDescriptor] = []
        while cursor < queue.count && cursor < 10000 {
            let (element, depth) = queue[cursor]; cursor += 1
            if attribute(element, kAXRoleAttribute) as? String == "AXTextArea" {
                candidates.append(element)
                descriptors.append(describe(element))
            }
            if depth < 40, let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] {
                queue.append(contentsOf: children.map { ($0, depth + 1) })
            }
        }
        let recognized = descriptors.filter { CodexComposerPolicy.recognizes($0) }
        if recognized.count == 1, let descriptor = recognized.first, let characters = descriptor.characters,
           characters > 0 && !descriptor.isEmpty {
            throw BridgeError("Codex 发送框已有未发送草稿，已保留，未粘贴。请先保存或处理草稿，再在空白发送框中重试")
        }
        guard cursor == queue.count, let index = CodexComposerPolicy.select(descriptors) else {
            throw BridgeError("未找到唯一、可编辑且为空的 Codex 发送框。请关闭搜索或弹窗、保留已有草稿，再在空白发送框中手动粘贴")
        }
        return candidates[index]
    }

    static func paste(_ prompt: String, into application: NSRunningApplication) async throws {
        let composer = try findEmpty(in: application)
        application.activate()
        guard AXUIElementSetAttributeValue(composer, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success else {
            throw BridgeError("无法聚焦 Codex 发送框，请手动粘贴")
        }
        try await Task.sleep(for: .milliseconds(150))
        let root = AXUIElementCreateApplication(application.processIdentifier)
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == application.processIdentifier,
              let focused = uiElement(attribute(root, kAXFocusedUIElementAttribute)), CFEqual(focused, composer),
              describe(composer).isEmpty else {
            throw BridgeError("Codex 焦点或草稿已变化，已停止自动粘贴")
        }
        guard NSPasteboard.general.string(forType: .string) == prompt else {
            throw BridgeError("剪贴板内容已变化，已停止自动粘贴")
        }
        guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 9, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: 9, keyDown: false) else {
            throw BridgeError("无法创建粘贴事件，请手动粘贴")
        }
        down.flags = .maskCommand; up.flags = .maskCommand
        down.postToPid(application.processIdentifier); up.postToPid(application.processIdentifier)
        for _ in 0..<20 {
            try await Task.sleep(for: .milliseconds(100))
            if let value = attribute(composer, kAXValueAttribute) as? String,
               CodexComposerPolicy.verifies(prompt, pasted: value) { return }
        }
        throw BridgeError("粘贴后正文未完整匹配，请检查 Codex 发送框；内容仍在剪贴板。不要重复发送")
    }
}
