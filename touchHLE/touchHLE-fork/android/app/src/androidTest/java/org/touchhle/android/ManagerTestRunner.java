package org.touchhle.android;

import android.app.Instrumentation;
import android.os.Bundle;
import android.app.Activity;
import org.json.JSONObject;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;

/** Runs against isolated cache fixtures, never the player's sandbox or settings. */
public class ManagerTestRunner extends Instrumentation {
    private int checks;
    private final StringBuilder report = new StringBuilder();
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    private void check(boolean value, String name) {
        if (!value) throw new AssertionError(name);
        checks++; report.append("PASS ").append(name).append('\n');
    }
    private interface Attempt { void run() throws Exception; }
    private void reject(Attempt action, String name) throws Exception {
        boolean rejected = false;
        try { action.run(); } catch (Exception e) { rejected = true; }
        check(rejected, name);
    }
    private static byte[] fixture() {
        byte[] b = new byte[512]; ByteBuffer v = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN); v.putInt(0, 14);
        byte[] marker = {1,9,0,0,0,0x55,0x4e,0x44,0x45,0x46,0x49,0x4e,0x45,0x44};
        System.arraycopy(marker, 0, b, 30, marker.length); v.putInt(30 + 0x42, 4); v.putInt(30 + 0x46, 200);
        v.putInt(30 + 0x56, 1); v.putInt(30 + 0x5a, 2); return b;
    }
    private static byte[] hostileZip(String id, String entry) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry("zf_backup.json"));
            zip.write(new JSONObject().put("format", 1).put("appId", id).put("offset", 0).toString().getBytes(StandardCharsets.UTF_8));
            zip.closeEntry(); zip.putNextEntry(new ZipEntry(entry)); zip.write(fixture()); zip.closeEntry();
        }
        return bytes.toByteArray();
    }
    @Override public void onStart() {
        Bundle result = new Bundle(); File root = new File(getTargetContext().getCacheDir(), "zf-manager-tests-" + UUID.randomUUID());
        try {
            root.mkdirs(); ZfStorage store = new ZfStorage(getTargetContext(), root, new File(root, "test.lock"));
            try (ZfStorage.Lease held = store.lock()) {
                check(store.gameRunning(), "exclusive lock blocks a second operation");
                store.ensureBundled(); ZfIpa ipa = store.selected(); String id = ipa.appId;
                check(id.equals("com.playforge.ZombieFarm.ZFR"), "bundled binary plist and executable");
                File xmlIpa = new File(root, "xml-fixture.zip");
                try (ZipOutputStream zip = new ZipOutputStream(new FileOutputStream(xmlIpa))) {
                    zip.putNextEntry(new ZipEntry("Payload/ZFR.app/Info.plist"));
                    zip.write(("<?xml version=\"1.0\"?><!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">"
                        + "<plist><dict><key>CFBundleIdentifier</key><string>com.playforge.ZombieFarm.ZFR</string>"
                        + "<key>CFBundleExecutable</key><string>ZFR</string><key>CFBundleVersion</key><string>1.0</string></dict></plist>")
                        .getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
                    zip.putNextEntry(new ZipEntry("Payload/ZFR.app/ZFR")); zip.write(new byte[]{1}); zip.closeEntry();
                }
                check(ZfIpa.read(xmlIpa).version.equals("1.0"), "XML IPA plist with external DTD");
                check(ZfStorage.hash(ipa.file).equals("e5951f945d23e88f25d0d1e7dc84e39ab524c566e28460173600ba05423c9ded"), "bundled IPA bytes unchanged");
                JSONObject app = new JSONObject().put("family", "ipad").put("scale", "3/2").put("fps", "120").put("fix", false);
                store.settings(id, app);
                JSONObject roundtrip = store.settings(id);
                check(roundtrip.getString("family").equals("ipad") && roundtrip.getString("scale").equals("3/2")
                    && roundtrip.getString("fps").equals("120") && !roundtrip.getBoolean("fix"), "settings round trip");
                check(store.advance(id, 3600) == 3600 && store.advance(id, 0) == 3600 && store.advance(id, 60) == 3660, "cumulative clock and normal launch");
                check(store.settings("com.playforge.ZombieFarmChinese").optLong("offset", 0) == 0, "per-game clock isolation");
                reject(() -> store.advance(id, Long.MAX_VALUE), "clock overflow refused");
                reject(() -> store.settings(id, new JSONObject().put("scale", "1/0")), "invalid scale refused");
                check(ZfStorage.scale("1.5") == ZfStorage.scale("3/2"), "fraction and decimal scale equivalent");
                byte[] original = fixture(); ZfStorage.atomic(store.live(id), original);
                File profile = new File(store.sandbox(id), "Documents/profile.txt");
                ZfStorage.atomic(profile, "original profile".getBytes(StandardCharsets.UTF_8));
                File preferences = new File(store.sandbox(id), "Library/Preferences/game.plist");
                ZfStorage.atomic(preferences, "original preferences".getBytes(StandardCharsets.UTF_8));
                File manual = store.backup(id, "manual");
                store.setCurrency(id, 123456, 654321); byte[] changed = ZfStorage.bytes(store.live(id));
                ZfSave money = store.currency(id);
                check(money.gold == 123456 && money.brains == 654321, "currency write readback");
                boolean onlyCurrency = changed.length == original.length;
                for (int i = 0; i < changed.length; i++)
                    if ((i < 30 + 0x46 || i >= 30 + 0x4e) && changed[i] != original[i]) onlyCurrency = false;
                check(onlyCurrency && ZfSave.read(original).gold == 200, "only currency bytes change, input remains untouched");
                check(store.backups(id).size() == 2, "currency creates full automatic backup");
                byte[] corrupt = Arrays.copyOf(original, original.length); corrupt[0] = 13;
                reject(() -> store.importSave(id, new ByteArrayInputStream(corrupt)), "unsupported save refused");
                check(Arrays.equals(changed, ZfStorage.bytes(store.live(id))), "failed import preserves live bytes");
                byte[] duplicated = Arrays.copyOf(original, original.length);
                System.arraycopy(original, 30, duplicated, 200, 14);
                reject(() -> ZfSave.read(duplicated), "ambiguous player block refused");
                reject(() -> ZfSave.read(Arrays.copyOf(original, 50)), "truncated save refused");
                reject(() -> ZfSave.edit(original, -1, 0), "negative currency refused");
                ZfStorage.atomic(profile, "changed profile".getBytes(StandardCharsets.UTF_8));
                store.advance(id, 7200);
                try (InputStream in = new FileInputStream(manual)) { store.restore(id, in); }
                check(Arrays.equals(original, ZfStorage.bytes(store.live(id))), "backup restores exact save bytes");
                check(new String(ZfStorage.bytes(profile), StandardCharsets.UTF_8).equals("original profile")
                    && new String(ZfStorage.bytes(preferences), StandardCharsets.UTF_8).equals("original preferences"), "backup restores profile and preferences");
                check(store.settings(id).getLong("offset") == 3660, "backup restores cumulative clock");
                byte[] traversal = hostileZip(id, "sandbox/../../escaped.bin");
                reject(() -> store.restore(id, new ByteArrayInputStream(traversal)), "zip traversal refused");
                check(!new File(root, "escaped.bin").exists() && Arrays.equals(original, ZfStorage.bytes(store.live(id))), "hostile backup leaves live data untouched");
                byte[] wrongId = hostileZip("com.playforge.ZombieFarmChinese", "sandbox/Documents/saveGame.bin2");
                reject(() -> store.restore(id, new ByteArrayInputStream(wrongId)), "cross-game backup refused");
                byte[] imported = ZfSave.edit(original, 999, 888);
                store.importSave(id, new ByteArrayInputStream(imported));
                check(Arrays.equals(imported, ZfStorage.bytes(store.live(id))), "raw save import exact readback");
                try (InputStream in = getTargetContext().getAssets().open(ZfStorage.BUNDLED)) {
                    ZfIpa added = store.importIpa(in, "测试版本.ipa");
                    check(store.versions().size() == 2 && store.selected().file.equals(added.file), "IPA import and version selection");
                }
                store.select(ipa); check(store.selected().file.equals(ipa.file), "switch back to bundled version");
                int count = store.backups(id).size(); store.deleteBackup(id, manual);
                check(store.backups(id).size() == count - 1, "delete one backup");
                reject(() -> store.deleteBackup(id, store.live(id)), "live save deletion refused");
            }
            check(!store.gameRunning(), "lock released after operation");
            result.putString("stream", "\n" + report + "RESULT: PASS (" + checks + " checks)\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable e) {
            StringWriter trace = new StringWriter(); e.printStackTrace(new PrintWriter(trace));
            result.putString("stream", "\n" + report + "RESULT: FAIL\n" + trace); finish(Activity.RESULT_CANCELED, result);
        } finally {
            try { ZfStorage.deleteTree(root); } catch (Exception ignored) {}
        }
    }
}
