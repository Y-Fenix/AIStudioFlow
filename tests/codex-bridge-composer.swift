import Foundation

@main
struct ComposerPolicyTests {
    static func main() {
        let composer = CodexComposerDescriptor(role: "AXTextArea", classes: ["ProseMirror"],
            ancestorClasses: [["_ComposerLayoutBody_boifs_2"]], enabled: true, characters: 0)
        let search = CodexComposerDescriptor(role: "AXTextField", classes: [],
            ancestorClasses: [], enabled: true, characters: 0)
        let otherEditor = CodexComposerDescriptor(role: "AXTextArea", classes: ["ProseMirror"],
            ancestorClasses: [["document-editor"]], enabled: true, characters: 0)
        var draft = composer; draft.characters = 12
        var disabled = composer; disabled.enabled = false
        var unknownContent = composer; unknownContent.characters = nil
        var placeholder = composer; placeholder.characters = 16; placeholder.placeholderOnly = true
        assert(CodexComposerPolicy.select([search, composer, otherEditor]) == 1)
        assert(CodexComposerPolicy.select([search, otherEditor]) == nil)
        assert(CodexComposerPolicy.select([composer, composer]) == nil)
        assert(CodexComposerPolicy.select([draft]) == nil)
        assert(CodexComposerPolicy.select([disabled]) == nil)
        assert(CodexComposerPolicy.select([unknownContent]) == nil)
        assert(CodexComposerPolicy.select([placeholder]) == 0)
        assert(CodexComposerPolicy.verifies("line 1\nline 2", pasted: "line 1\nline 2"))
        assert(!CodexComposerPolicy.verifies("full content", pasted: "full"))
        assert(!CodexComposerPolicy.verifies("full content", pasted: "draftfull content"))
        print("Codex composer selection, draft protection and paste verification checks passed")
    }
}
