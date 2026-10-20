#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEngine;

// 仅在用户手动连接后处理本地任务；不会启动或退出Play Mode。
[InitializeOnLoad]
public static class TestFlowEditorBridge {
    const string Key = "TestFlow.Mailbox.";
    static string Root => SessionState.GetString(Key + Application.dataPath, "");
    static double nextPoll;
    static string active;
    static EditorWindow window;
    static FieldInfo running, directory;
    [Serializable] public sealed class Request {
        public string id, mode, projectRoot, runnerSha256;
        public long expiresUnix;
    }
    [Serializable] public sealed class Result {
        public string id, status, detail, reportJson, runnerSha256;
    }
    [Serializable] public sealed class Heartbeat {
        public string projectRoot, runnerSha256;
        public long unix;
        public bool playing, paused, compiling;
    }
    static TestFlowEditorBridge() { EditorApplication.update += Tick; }

    [MenuItem("Tools/TestFlow/连接本机平台邮箱")]
    static void Connect() {
        if (active != null) return;
        var folder = EditorUtility.OpenFolderPanel("选择 AutoTest/data/editor-bridge 目录", "", "");
        if (string.IsNullOrEmpty(folder)) return;
        if (!EditorUtility.DisplayDialog("TestFlow", "连接后仅接受设置冒烟任务。测试占用鼠标并切换/恢复音乐音效；请先停在正式首页。不会启动游戏、运行GM或更改账号。", "连接", "取消")) return;
        Directory.CreateDirectory(folder);
        SessionState.SetString(Key + Application.dataPath, Path.GetFullPath(folder));
    }
    [MenuItem("Tools/TestFlow/断开本机平台邮箱")]
    static void Disconnect() {
        if (active != null) {
            EditorUtility.DisplayDialog("TestFlow", "测试正在执行。请先在原测试窗口停止并核对设置恢复；断开连接不会自动清除运行证据。", "确定");
            return;
        }
        SessionState.EraseString(Key + Application.dataPath);
    }
    static string Hash(string path) {
        using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-", "").ToLowerInvariant();
    }
    static void Save(string folder, Result result) {
        var path = Path.Combine(folder, result.id + ".result.json");
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonUtility.ToJson(result, true), new UTF8Encoding(false));
        if (File.Exists(path)) File.Delete(path);
        File.Move(temporary, path);
    }
    static void Tick() {
        if (EditorApplication.timeSinceStartup < nextPoll) return;
        nextPoll = EditorApplication.timeSinceStartup + 1;
        var folder = Root;
        if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return;
        var runnerFile = Path.Combine(Application.dataPath, "Editor/Tools/TEST/TEST_RealGameUiSmokeWindow.cs");
        File.WriteAllText(Path.Combine(folder, "heartbeat.json"), JsonUtility.ToJson(new Heartbeat {
            projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, "..")),
            runnerSha256 = File.Exists(runnerFile) ? Hash(runnerFile) : "",
            unix = DateTimeOffset.UtcNow.ToUnixTimeSeconds(), playing = EditorApplication.isPlaying,
            paused = EditorApplication.isPaused, compiling = EditorApplication.isCompiling
        }), new UTF8Encoding(false));
        if (active != null) {
            try {
                if (window == null) throw new InvalidOperationException("测试窗口已关闭，结果不确定，请核对设置恢复");
                if ((bool)running.GetValue(window)) return;
                var report = Path.Combine((string)directory.GetValue(window), "report.json");
                if (!File.Exists(report)) throw new InvalidOperationException("测试结束但缺少本次报告");
                var old = JsonUtility.FromJson<Result>(File.ReadAllText(Path.Combine(folder, active + ".result.json")));
                old.status = "completed"; old.reportJson = File.ReadAllText(report);
                Save(folder, old);
            } catch (Exception e) { Save(folder, new Result { id = active, status = "uncertain", detail = e.Message }); }
            active = null; window = null;
            return;
        }
        // claimed文件作为永久领取记录；域重载后没有终态报告的任务必须人工核对，禁止重跑。
        if (Directory.GetFiles(folder, "*.claimed.json").Any(path => {
            try {
            var id = Path.GetFileName(path).Replace(".claimed.json", "");
            var result = Path.Combine(folder, id + ".result.json");
            if (!File.Exists(result)) return true;
            var status = JsonUtility.FromJson<Result>(File.ReadAllText(result)).status;
            return status != "completed" && status != "rejected";
            } catch { return true; }
        })) return;
        var input = Directory.GetFiles(folder, "*.request.json").OrderBy(path => path).FirstOrDefault();
        if (input == null) return;
        var idFromFile = Path.GetFileName(input).Replace(".request.json", "");
        Guid parsed;
        if (!Guid.TryParseExact(idFromFile, "N", out parsed)) return;
        var claimed = Path.Combine(folder, idFromFile + ".claimed.json");
        if (File.Exists(claimed)) return;
        File.Move(input, claimed);
        try {
            var request = JsonUtility.FromJson<Request>(File.ReadAllText(claimed));
            if (request == null || request.id != idFromFile || request.mode != "settings_smoke") throw new InvalidOperationException("任务标识或模式不支持");
            var project = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            if (Path.GetFullPath(request.projectRoot) != project) throw new InvalidOperationException("目标项目不一致");
            var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            if (now > request.expiresUnix || request.expiresUnix > now + 120) throw new InvalidOperationException("任务已过期或有效期不支持，未执行");
            if (!EditorApplication.isPlaying || EditorApplication.isCompiling || EditorApplication.isPaused) throw new InvalidOperationException("需要已运行且未暂停的Play Mode");
            var runner = Path.Combine(Application.dataPath, "Editor/Tools/TEST/TEST_RealGameUiSmokeWindow.cs");
            if (Hash(runner) != request.runnerSha256) throw new InvalidOperationException("运行器源码已变化");
            var type = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType("GagaSort.UiAutomation.TEST_RealGameUiSmokeWindow")).FirstOrDefault(t => t != null);
            if (type == null) throw new InvalidOperationException("未找到既有测试窗口");
            const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
            running = type.GetField("mRunning", flags); directory = type.GetField("mDirectory", flags);
            var traversal = type.GetField("mTraversal", flags); var start = type.GetMethod("StartRun", flags);
            var gm = type.GetField("mGmProcess", flags);
            if (running == null || directory == null || traversal == null || start == null || gm == null) throw new InvalidOperationException("运行器协议已变化");
            window = EditorWindow.GetWindow(type);
            if ((bool)running.GetValue(window) || gm.GetValue(window) != null) throw new InvalidOperationException("已有测试或GM操作运行中");
            traversal.SetValue(window, false);
            Save(folder, new Result { id = request.id, status = "running", runnerSha256 = request.runnerSha256 });
            active = request.id;
            start.Invoke(window, null);
        } catch (Exception e) {
            Save(folder, new Result { id = idFromFile, status = active == null ? "rejected" : "uncertain", detail = e.GetBaseException().Message });
            active = null; window = null;
        }
    }
}
#endif
