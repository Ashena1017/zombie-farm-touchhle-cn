/* This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.provider.OpenableColumns;
import androidx.activity.result.ActivityResult;
import androidx.appcompat.app.AppCompatActivity;
import app.tauri.annotation.ActivityCallback;
import app.tauri.annotation.Command;
import app.tauri.annotation.TauriPlugin;
import app.tauri.plugin.Invoke;
import app.tauri.plugin.JSObject;
import app.tauri.plugin.Plugin;
import java.io.*;
import java.text.DateFormat;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

@TauriPlugin
public final class ManagerPlugin extends Plugin {
    private final Activity activity;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private ZfStorage storage;
    private String initialWarning;
    private boolean installed;

    public ManagerPlugin(Activity activity) { super(activity); this.activity = activity; }

    @Override public void onDestroy(AppCompatActivity ignored) { worker.shutdown(); }

    private static JSONObject obj(Object... pairs) throws JSONException {
        JSONObject out = new JSONObject();
        for (int i = 0; i < pairs.length; i += 2) out.put((String)pairs[i], pairs[i + 1]);
        return out;
    }

    private interface Operation { JSONObject run() throws Exception; }
    private void submit(Invoke call, Operation op) {
        worker.execute(() -> {
            try {
                if (storage == null) storage = new ZfStorage(activity);
                call.resolve(new JSObject(op.run().toString()));
            } catch (Exception ex) { call.reject(ex.getMessage(), ex); }
        });
    }

    @Command public void dispatch(Invoke call) throws Exception {
        JSONObject args = call.getArgs();
        String action = args.getString("action");
        JSONObject data = args.getJSONObject("data");
        if (action.equals("browseIpa") || action.equals("importSave") || action.equals("exportBackup")) {
            boolean export = action.equals("exportBackup");
            Intent intent = new Intent(export ? Intent.ACTION_CREATE_DOCUMENT : Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType(export ? "application/zip" : "*/*");
            if (export) intent.putExtra(Intent.EXTRA_TITLE, data.getString("name"));
            activity.runOnUiThread(() -> {
                try { startActivityForResult(call, intent, "filePicked"); }
                catch (Exception ex) { call.reject(ex.getMessage(), ex); }
            });
        } else if (action.equals("openProject")) {
            activity.runOnUiThread(() -> {
                try {
                    activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/Ashena1017/zombie-farm-touchhle-cn")));
                    call.resolve();
                } catch (Exception ex) { call.reject(ex.getMessage(), ex); }
            });
        } else submit(call, () -> execute(action, data));
    }

    @ActivityCallback public void filePicked(Invoke call, ActivityResult result) {
        submit(call, () -> {
            Uri uri = result.getData() == null ? null : result.getData().getData();
            if (result.getResultCode() != Activity.RESULT_OK || uri == null) return snapshot();
            JSONObject args = call.getArgs(), data = args.getJSONObject("data");
            try (ZfStorage.Lease ignored = storage.lock()) {
                String action = args.getString("action");
                if (action.equals("browseIpa")) {
                    String name = "导入文件.ipa";
                    try (Cursor cursor = activity.getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                        if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) name = cursor.getString(0);
                    }
                    try (InputStream in = activity.getContentResolver().openInputStream(uri)) { storage.importIpa(in, name); }
                } else {
                    String id = storage.selected().appId;
                    if (!id.equals(data.getString("appId"))) throw new IOException("所选游戏版本已改变");
                    if (action.equals("exportBackup")) {
                        try (InputStream in = new FileInputStream(backup(id, data.getString("name")));
                             OutputStream out = activity.getContentResolver().openOutputStream(uri, "wt")) {
                            ZfStorage.copy(in, out, ZfStorage.MAX_BACKUP_ARCHIVE_BYTES);
                        }
                    } else {
                        try (BufferedInputStream in = new BufferedInputStream(activity.getContentResolver().openInputStream(uri))) {
                            in.mark(2);
                            boolean zip = in.read() == 'P' && in.read() == 'K';
                            in.reset();
                            if (zip) storage.restore(id, in); else storage.importSave(id, in);
                        }
                    }
                }
            }
            return snapshot();
        });
    }

    private JSONObject execute(String action, JSONObject data) throws Exception {
        switch (action) {
            case "appearance": case "setAppearance": return appearance(action, data);
            case "verify": return verify();
            case "gameRunning": return obj("running", storage.gameRunning());
            case "snapshot":
                if (!installed && !storage.gameRunning()) {
                    try (ZfStorage.Lease ignored = storage.lock()) { initialWarning = storage.ensureBundled(); }
                    installed = true;
                }
                return snapshot();
        }
        try (ZfStorage.Lease ignored = storage.lock()) {
            if (action.equals("selectIpa")) {
                boolean found = false;
                for (ZfIpa item : storage.versions()) if (item.file.getName().equals(data.getString("path"))) {
                    storage.select(item); found = true; break;
                }
                if (!found) throw new IOException("所选 IPA 不存在");
            } else {
                String id = storage.selected().appId;
                JSONObject prefs = storage.settings(id);
                switch (action) {
                    case "setSetting":
                        String value = data.getString("value");
                        switch (data.getString("key")) {
                            case "window_family": prefs.put("family", value); break;
                            case "window_scale": prefs.put("scale", value); break;
                            case "fps_limit": prefs.put("fps", value); break;
                            case "run_loop_fix": prefs.put("fix", value.equals("1")); break;
                            default: throw new IOException("未知设置");
                        }
                        storage.settings(id, prefs);
                        return obj("settings", settings(prefs));
                    case "resetTime": storage.settings(id, prefs.put("offset", 0)); break;
                    case "launch":
                        if (!data.optBoolean("allowModified")) {
                            JSONObject check = verifyLocked();
                            if (!check.getString("level").equals("ok"))
                                return obj("started", false, "warning", check.getString("text"));
                        }
                        int hours = data.getInt("hours"), minutes = data.getInt("minutes");
                        if (hours < 0 || hours > 100000 || minutes < 0 || minutes > 59) throw new IOException("无效的快进时间");
                        if (data.optBoolean("remember")) prefs.put("skipHours", hours).put("skipMinutes", minutes);
                        storage.advance(id, hours * 3600L + minutes * 60L, prefs);
                        break;
                    case "backup": storage.backup(id, "手动"); break;
                    case "restore":
                        try (InputStream in = new FileInputStream(backup(id, data.getString("name")))) { storage.restore(id, in); }
                        break;
                    case "delete":
                        JSONArray names = data.getJSONArray("names");
                        List<File> selected = new ArrayList<>();
                        Map<String, File> available = new HashMap<>();
                        for (File f : storage.backups(id)) available.put(f.getName(), f);
                        for (int i = 0; i < names.length(); i++) {
                            File f = available.remove(names.getString(i));
                            if (f == null) throw new IOException("备份记录已改变");
                            selected.add(f);
                        }
                        for (File f : selected) storage.deleteBackup(id, f);
                        break;
                    case "setCurrency": storage.setCurrency(id, data.getInt("gold"), data.getInt("brains")); break;
                    default: throw new IOException("未知操作");
                }
            }
        }
        if (action.equals("launch")) {
            activity.runOnUiThread(() -> activity.startActivity(new Intent(activity, MainActivity.class)));
            return obj("started", true);
        }
        return snapshot();
    }

    private File backup(String id, String name) throws Exception {
        for (File file : storage.backups(id)) if (file.getName().equals(name)) return file;
        throw new IOException("备份记录已改变");
    }

    private static JSONObject settings(JSONObject p) throws Exception {
        return obj("window_family", p.optString("family", ZfStorage.DEFAULT_FAMILY),
            "window_scale", ZfStorage.validScaleOrDefault(p.optString("scale", ZfStorage.DEFAULT_SCALE)),
            "fps_limit", p.optString("fps", "60"), "run_loop_fix", p.optBoolean("fix", true) ? "1" : "0");
    }

    private JSONObject snapshot() throws Exception {
        List<ZfIpa> versions = storage.versions();
        ZfIpa selected = storage.selectedFrom(versions);
        JSONArray ipas = new JSONArray(), saves = new JSONArray();
        for (ZfIpa item : versions) ipas.put(obj("name", item.name, "path", item.file.getName(), "appId", item.appId, "version", item.version));
        boolean running = storage.gameRunning();
        JSONObject prefs = new JSONObject(), currency = null;
        if (selected != null) {
            String id = selected.appId;
            prefs = storage.settings(id);
            File live = storage.live(id);
            if (!running && live.isFile()) {
                saves.put(fileInfo(live, true));
                try {
                    ZfSave values = storage.currency(id);
                    currency = obj("gold", values.gold, "brains", values.brains);
                } catch (Exception invalidSave) { /* retain access to backups */ }
            }
            for (File file : storage.backups(id)) saves.put(fileInfo(file, false));
        }
        return obj("ipas", ipas, "selected", selected == null ? null : selected.file.getName(),
            "appId", selected == null ? null : selected.appId, "running", running, "settings", settings(prefs),
            "offset", prefs.optLong("offset", 0), "skip", obj("hours", prefs.optInt("skipHours", 6), "minutes", prefs.optInt("skipMinutes", 0)),
            "saves", saves, "currency", currency);
    }

    private static JSONObject fileInfo(File file, boolean live) throws Exception {
        return obj("name", file.getName(), "size", file.length(), "modified", DateFormat.getDateTimeInstance().format(new Date(file.lastModified())),
            "kind", live ? "当前存档" : "完整备份", "live", live);
    }

    private JSONObject appearance(String action, JSONObject data) throws Exception {
        ZfAppearance p = new ZfAppearance(activity.getSharedPreferences(ManagerActivity.class.getName(), Activity.MODE_PRIVATE));
        if (action.equals("setAppearance")) {
            String theme = data.getString("theme");
            if (!Arrays.asList("system","light","dark").contains(theme)) throw new IOException("无效的主题");
            p.mode = theme;
            p.custom = Color.parseColor(data.getString("custom"));
            p.choice = ZfAppearance.CUSTOM;
            if (!data.getBoolean("isCustom")) {
                int accent = Color.parseColor(data.getString("accent"));
                for (int i = 0; i < ZfAppearance.COLORS.length; i++) if (ZfAppearance.COLORS[i] == accent) p.choice = i;
                if (p.choice < 0) throw new IOException("无效的预设颜色");
            }
            p.save();
        }
        return obj("theme", p.mode, "accent", hexColor(p.accent()), "custom", hexColor(p.custom),
            "isCustom", p.choice == ZfAppearance.CUSTOM, "notice", true);
    }

    private static String hexColor(int color) { return String.format(Locale.ROOT, "#%06X", color & 0xffffff); }

    private JSONObject verify() throws Exception {
        try (ZfStorage.Lease ignored = storage.lock()) { return verifyLocked(); }
    }

    private JSONObject verifyLocked() throws Exception {
        String warning = storage.ensureBundled();
        if (initialWarning != null) {
            if (warning == null) warning = initialWarning;
            initialWarning = null;
        }
        String cert = ManagerActivity.signatureOfSelf(activity);
        boolean signed = ManagerActivity.OFFICIAL_CERT.equalsIgnoreCase(cert);
        JSONArray rows = new JSONArray();
        rows.put(obj("name", "Android 安装包签名", "expected", ManagerActivity.OFFICIAL_CERT, "actual", cert, "state", signed ? "ok" : "bad"));
        rows.put(obj("name", ZfStorage.BUNDLED, "expected", BuildConfig.BUNDLED_IPA_SHA256, "state", warning == null ? "ok" : "bad"));
        boolean ok = signed && warning == null;
        return obj("rows", rows, "level", ok ? "ok" : "warn", "text", ok ? "签名与内置 IPA 均与官方一致。" :
            "你拿到的可能是改版。" + (signed ? "" : "安装包签名异常。") + (warning == null ? "" : warning));
    }
}
