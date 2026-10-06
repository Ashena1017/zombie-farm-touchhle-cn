/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.*;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.zip.*;

/** Manager operations share an exclusive lock with the separate game process. */
public final class ZfStorage {
    public static final String BUNDLED = "Zombie_Farm_v29fix.ipa";
    public final File root, apps;
    private final Context context;
    private final File lockFile;
    public ZfStorage(Context context) throws IOException {
        this(context, context.getExternalFilesDir(null), new File(context.getFilesDir(), "zf_game.lock"));
    }
    // Allows instrumentation to exercise real Android I/O in an isolated fixture directory.
    ZfStorage(Context context, File root, File lockFile) throws IOException {
        if (root == null) throw new IOException("应用存储暂不可用");
        this.context = context; this.root = root; this.lockFile = lockFile;
        apps = new File(root, "touchHLE_apps"); mkdir(apps);
    }
    public static final class Lease implements AutoCloseable {
        private final RandomAccessFile file; private final FileLock lock;
        Lease(RandomAccessFile file, FileLock lock) { this.file = file; this.lock = lock; }
        @Override public void close() throws IOException { try { lock.release(); } finally { file.close(); } }
    }
    public Lease lock() throws IOException {
        RandomAccessFile file = new RandomAccessFile(lockFile, "rw");
        try {
            FileLock lock = file.getChannel().tryLock();
            if (lock == null) throw new IOException("游戏正在运行，请先退出游戏再操作");
            return new Lease(file, lock);
        } catch (IOException | OverlappingFileLockException e) {
            file.close(); throw new IOException("游戏或存档操作正在进行，请稍后再试", e);
        }
    }
    public boolean gameRunning() {
        try (Lease ignored = lock()) { return false; } catch (IOException e) { return true; }
    }
    private static void mkdir(File file) throws IOException {
        if (!file.isDirectory() && !file.mkdirs()) throw new IOException("无法创建目录 " + file.getName());
    }
    public static byte[] bytes(File file) throws IOException {
        try (InputStream in = new FileInputStream(file)) { return ZfIpa.readLimited(in, 16 * 1024 * 1024); }
    }
    static void atomic(File file, byte[] data) throws IOException {
        mkdir(file.getParentFile()); AtomicFile writer = new AtomicFile(file);
        FileOutputStream out = null;
        try { out = writer.startWrite(); out.write(data); writer.finishWrite(out); }
        catch (IOException e) { writer.failWrite(out); throw e; }
    }
    public static String hash(File file) throws Exception {
        MessageDigest sha = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] b = new byte[65536]; int n;
            while ((n = in.read(b)) != -1) sha.update(b, 0, n);
        }
        StringBuilder s = new StringBuilder();
        for (byte b : sha.digest()) s.append(String.format(Locale.ROOT, "%02x", b & 255));
        return s.toString();
    }
    public void ensureBundled() throws Exception {
        String expected;
        try (InputStream in = context.getAssets().open("touchHLE_zombiefarm_ipa.sha256")) {
            expected = new String(ZfIpa.readLimited(in, 1024), StandardCharsets.US_ASCII).trim();
        }
        File target = new File(apps, BUNDLED), stamp = new File(apps, BUNDLED + ".sha256");
        if (target.isFile() && stamp.isFile()
                && new String(bytes(stamp), StandardCharsets.US_ASCII).trim().equals(expected)
                && hash(target).equals(expected)) return;
        File temp = File.createTempFile("bundled-", ".ipa", apps);
        try {
            try (InputStream in = context.getAssets().open(BUNDLED); FileOutputStream out = new FileOutputStream(temp)) {
                copy(in, out, 512L * 1024 * 1024); out.getFD().sync();
            }
            if (!hash(temp).equals(expected)) throw new IOException("内置 IPA 校验失败");
            ZfIpa.read(temp);
            android.system.Os.rename(temp.getPath(), target.getPath());
            atomic(stamp, expected.getBytes(StandardCharsets.US_ASCII));
        } finally { temp.delete(); }
    }
    private JSONObject config() throws Exception {
        AtomicFile file = new AtomicFile(new File(root, "zf_manager.json"));
        try (InputStream in = file.openRead()) {
            return new JSONObject(new String(ZfIpa.readLimited(in, 1024 * 1024), StandardCharsets.UTF_8));
        } catch (FileNotFoundException e) { return new JSONObject(); }
    }
    private void writeConfig(JSONObject config) throws Exception {
        atomic(new File(root, "zf_manager.json"), config.toString().getBytes(StandardCharsets.UTF_8));
    }
    public List<ZfIpa> versions() throws Exception {
        List<ZfIpa> result = new ArrayList<>(); File[] files = apps.listFiles();
        if (files != null) for (File file : files) {
            if (!file.getName().endsWith(".ipa")) continue;
            try { result.add(ZfIpa.read(file)); } catch (Exception ignored) { /* never offer a damaged IPA */ }
        }
        result.sort(Comparator.comparing((ZfIpa i) -> !i.file.getName().equals(BUNDLED))
            .thenComparing(i -> i.name));
        return result;
    }
    public ZfIpa selected() throws Exception {
        String name = config().optString("selected", BUNDLED);
        if (name.contains("/") || name.contains("\\")) throw new IOException("版本选择无效");
        File file = new File(apps, name);
        if (!file.isFile()) file = new File(apps, BUNDLED);
        return ZfIpa.read(file);
    }
    public void select(ZfIpa ipa) throws Exception {
        if (!ipa.file.getCanonicalFile().getParentFile().equals(apps.getCanonicalFile()))
            throw new IOException("版本不在应用目录中");
        JSONObject config = config(); config.put("selected", ipa.file.getName()); writeConfig(config);
    }
    public ZfIpa importIpa(InputStream in, String displayName) throws Exception {
        File temp = File.createTempFile("import-", ".tmp", apps);
        try {
            try (FileOutputStream out = new FileOutputStream(temp)) { copy(in, out, 512L * 1024 * 1024); out.getFD().sync(); }
            ZfIpa.read(temp);
            String safeName = displayName.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_");
            if (!safeName.toLowerCase(Locale.ROOT).endsWith(".ipa")) safeName += ".ipa";
            if (safeName.length() > 100) safeName = safeName.substring(0, 96) + ".ipa";
            File target = new File(apps, hash(temp).substring(0, 12) + "_" + safeName);
            android.system.Os.rename(temp.getPath(), target.getPath());
            ZfIpa ipa = ZfIpa.read(target); select(ipa); return ipa;
        } finally { temp.delete(); }
    }
    public JSONObject settings(String id) throws Exception {
        JSONObject app = config().optJSONObject(id);
        return app == null ? new JSONObject() : new JSONObject(app.toString());
    }
    public void settings(String id, JSONObject app) throws Exception {
        validate(app); JSONObject config = config(); config.put(id, app); writeConfig(config);
    }
    public static double scale(String value) {
        try {
            if (!value.matches("[0-9]+(\\.[0-9]+)?|[0-9]+/[0-9]+")) throw new NumberFormatException();
            String[] parts = value.split("/");
            double n = Double.parseDouble(parts[0]);
            if (parts.length == 2) {
                int denominator = Integer.parseInt(parts[1]);
                if (denominator <= 0 || denominator > 10000 || n > 10000) throw new NumberFormatException();
                n /= denominator;
            }
            if (!Double.isFinite(n) || n < 1 || n > 3 || value.length() > 12) throw new NumberFormatException();
            return n;
        } catch (NumberFormatException e) { throw new IllegalArgumentException("倍率请填 1～3 的小数或分数，例如 1.5、3/2"); }
    }
    private static void validate(JSONObject app) throws Exception {
        if (!Arrays.asList("iphone", "ipad").contains(app.optString("family", "iphone")))
            throw new IllegalArgumentException("设备类型无效");
        scale(app.optString("scale", "1"));
        String fps = app.optString("fps", "60");
        if (!fps.equals("off")) {
            int number = Integer.parseInt(fps);
            if (number < 1 || number > 1000) throw new IllegalArgumentException("帧率请填 1～1000");
        }
        if (app.optLong("offset", 0) < 0) throw new IllegalArgumentException("累计跳过时间无效");
    }
    public long advance(String id, long seconds) throws Exception {
        JSONObject app = settings(id); long before = app.optLong("offset", 0);
        if (seconds < 0 || before < 0 || seconds > Long.MAX_VALUE - before
                || seconds + before > 2147483000L - System.currentTimeMillis() / 1000)
            throw new IllegalArgumentException("累计时间超出游戏支持范围");
        app.put("offset", before + seconds); settings(id, app); return before + seconds;
    }
    public File sandbox(String id) throws IOException {
        if (!id.matches("com\\.playforge\\.[A-Za-z0-9.]+")) throw new IOException("应用标识无效");
        return new File(new File(root, "touchHLE_sandbox"), id);
    }
    public File live(String id) throws IOException { return new File(sandbox(id), "Documents/saveGame.bin2"); }
    public ZfSave currency(String id) throws Exception { return ZfSave.read(bytes(live(id))); }
    private File backupDir(String id) throws IOException { File dir = new File(new File(root, "zf_backups"), id); mkdir(dir); return dir; }
    public List<File> backups(String id) throws IOException {
        File[] files = backupDir(id).listFiles((dir, name) -> name.endsWith(".zip"));
        List<File> result = files == null ? new ArrayList<>() : new ArrayList<>(Arrays.asList(files));
        result.sort(Comparator.comparing(File::getName).reversed()); return result;
    }
    public File backup(String id, String kind) throws Exception {
        if (!live(id).isFile()) throw new IOException("还没有存档，请先进入游戏创建存档");
        String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss-SSS", Locale.ROOT).format(new Date());
        File target = new File(backupDir(id), stamp + "_" + kind + "_" + UUID.randomUUID().toString().substring(0, 4) + ".zip");
        File temp = new File(target.getPath() + ".tmp");
        try {
            try (FileOutputStream file = new FileOutputStream(temp); ZipOutputStream zip = new ZipOutputStream(file)) {
                JSONObject metadata = new JSONObject().put("format", 1).put("appId", id)
                    .put("offset", settings(id).optLong("offset", 0));
                zip.putNextEntry(new ZipEntry("zf_backup.json"));
                zip.write(metadata.toString().getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
                zipDirectory(zip, sandbox(id), "sandbox/"); zip.finish(); file.getFD().sync();
            }
            android.system.Os.rename(temp.getPath(), target.getPath()); return target;
        } finally { temp.delete(); }
    }
    private static void zipDirectory(ZipOutputStream zip, File dir, String prefix) throws IOException {
        File[] children = dir.listFiles();
        if (children == null) throw new IOException("无法读取存档目录");
        for (File child : children) {
            if (!child.getCanonicalFile().getParentFile().equals(dir.getCanonicalFile())) throw new IOException("存档路径无效");
            if (child.isDirectory()) zipDirectory(zip, child, prefix + child.getName() + "/");
            else {
                zip.putNextEntry(new ZipEntry(prefix + child.getName()));
                try (InputStream in = new FileInputStream(child)) { copy(in, zip, 128L * 1024 * 1024); }
                zip.closeEntry();
            }
        }
    }
    public File setCurrency(String id, int gold, int brains) throws Exception {
        File save = live(id); byte[] original = bytes(save), updated = ZfSave.edit(original, gold, brains);
        File backup = backup(id, "改货币前");
        try {
            atomic(save, updated);
            if (!Arrays.equals(bytes(save), updated)) throw new IOException("存档写入后校验失败");
        } catch (Exception e) { atomic(save, original); throw e; }
        return backup;
    }
    public void importSave(String id, InputStream in) throws Exception {
        byte[] imported = ZfIpa.readLimited(in, 16 * 1024 * 1024); ZfSave.read(imported);
        File save = live(id); byte[] original = save.isFile() ? bytes(save) : null;
        if (original != null) backup(id, "导入前");
        try {
            atomic(save, imported);
            if (!Arrays.equals(bytes(save), imported)) throw new IOException("导入后校验失败");
        } catch (Exception e) {
            if (original != null) atomic(save, original); else save.delete();
            throw e;
        }
    }
    public void restore(String id, InputStream input) throws Exception {
        File stage = new File(root, ".zf-restore-" + UUID.randomUUID()), incoming = new File(stage, "sandbox");
        mkdir(stage); JSONObject metadata = null; Set<String> names = new HashSet<>(); long total = 0;
        File old = new File(sandbox(id).getPath() + ".before-restore-" + UUID.randomUUID());
        boolean moved = false, installed = false;
        JSONObject oldSettings = settings(id);
        try {
            try (ZipInputStream zip = new ZipInputStream(input)) {
                ZipEntry entry;
                while ((entry = zip.getNextEntry()) != null) {
                    String name = entry.getName();
                    if (!names.add(name) || names.size() > 10000 || name.contains("\\")) throw new IOException("备份目录无效");
                    if (name.equals("zf_backup.json")) {
                        metadata = new JSONObject(new String(ZfIpa.readLimited(zip, 65536), StandardCharsets.UTF_8));
                    } else {
                        if (!name.startsWith("sandbox/")) throw new IOException("备份包含未知文件");
                        File target = new File(stage, name);
                        if (!target.getCanonicalPath().startsWith(incoming.getCanonicalPath() + File.separator))
                            throw new IOException("备份包含越界路径");
                        if (entry.isDirectory()) mkdir(target);
                        else {
                            mkdir(target.getParentFile());
                            try (FileOutputStream out = new FileOutputStream(target)) {
                                total += copy(zip, out, 128L * 1024 * 1024 - total);
                            }
                        }
                    }
                    zip.closeEntry();
                }
            }
            if (metadata == null || metadata.optInt("format") != 1 || !id.equals(metadata.optString("appId")))
                throw new IOException("请选择当前游戏版本的 ZF 存档备份");
            ZfSave.read(bytes(new File(incoming, "Documents/saveGame.bin2")));
            long offset = metadata.optLong("offset", -1);
            if (offset < 0 || offset > 2147483000L - System.currentTimeMillis() / 1000)
                throw new IOException("备份的累计时间无效");
            File current = sandbox(id); mkdir(current.getParentFile());
            if (current.exists()) {
                backup(id, "恢复前");
                if (!current.renameTo(old)) throw new IOException("无法归档当前存档");
                moved = true;
            }
            if (!incoming.renameTo(current)) throw new IOException("无法安装备份存档");
            installed = true;
            settings(id, new JSONObject(oldSettings.toString()).put("offset", offset));
        } catch (Exception e) {
            if (installed) deleteTree(sandbox(id));
            if (moved && !old.renameTo(sandbox(id))) throw new IOException("恢复失败，原存档保留在 " + old.getName(), e);
            throw e;
        } finally {
            deleteTree(stage);
            if (installed && sandbox(id).exists()) deleteTree(old);
        }
    }
    public void deleteBackup(String id, File file) throws IOException {
        if (!file.getCanonicalFile().getParentFile().equals(backupDir(id).getCanonicalFile())
                || !file.getName().endsWith(".zip") || !file.delete()) throw new IOException("无法删除该备份");
    }
    static long copy(InputStream in, OutputStream out, long maximum) throws IOException {
        byte[] b = new byte[65536]; int n; long size = 0;
        while ((n = in.read(b)) != -1) {
            size += n; if (size > maximum) throw new IOException("文件大小超出限制"); out.write(b, 0, n);
        }
        return size;
    }
    static void deleteTree(File file) throws IOException {
        if (!file.exists()) return;
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children == null) throw new IOException("无法读取临时目录");
            for (File child : children) {
                if (!child.getCanonicalFile().getParentFile().equals(file.getCanonicalFile())) throw new IOException("临时目录路径无效");
                deleteTree(child);
            }
        }
        if (!file.delete()) throw new IOException("无法删除临时文件 " + file.getName());
    }
}
