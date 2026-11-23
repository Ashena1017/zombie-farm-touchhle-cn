/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.content.Context;
import android.util.AtomicFile;
import android.util.Log;
import org.json.JSONObject;
import java.io.*;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.zip.*;

/** Manager operations share an exclusive lock with the separate game process. */
public final class ZfStorage {
    public static final String BUNDLED = "Zombie_Farm_v29fix.ipa";
    static final String DEFAULT_FAMILY = "iphone";
    static final String DEFAULT_SCALE = "3";
    static final long MAX_GAME_EPOCH = 2147483000L;
    private static final int MAX_SAVE_BYTES = 16 * 1024 * 1024;
    private static final long MAX_BACKUP_DATA_BYTES = 128L * 1024 * 1024;
    static final long MAX_BACKUP_ARCHIVE_BYTES = 144L * 1024 * 1024;
    private static final int MAX_BACKUP_ENTRIES = 10000;
    private static final int MAX_BACKUP_METADATA_BYTES = 65536;
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
        try (InputStream in = new FileInputStream(file)) { return ZfIpa.readLimited(in, MAX_SAVE_BYTES); }
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
        return hex(sha.digest());
    }
    private static String hex(byte[] bytes) {
        StringBuilder s = new StringBuilder();
        for (byte b : bytes) s.append(String.format(Locale.ROOT, "%02x", b & 255));
        return s.toString();
    }
    /** Prepare the asset for the manager UI. The game process verifies the bytes before use. */
    public void prepareBundled() throws Exception { ensureBundled(false); }

    public void ensureBundled() throws Exception {
        ensureBundled(true);
    }
    private void ensureBundled(boolean verifyInstalledBytes) throws Exception {
        String expected;
        try (InputStream in = context.getAssets().open("touchHLE_zombiefarm_ipa.sha256")) {
            expected = new String(ZfIpa.readLimited(in, 1024), StandardCharsets.US_ASCII).trim();
        }
        File target = new File(apps, BUNDLED), stamp = new File(apps, BUNDLED + ".sha256");
        if (target.isFile() && stamp.isFile()
                && new String(bytes(stamp), StandardCharsets.US_ASCII).trim().equals(expected)) {
            if (verifyInstalledBytes) {
                if (hash(target).equals(expected)) return;
            } else {
                try {
                    ZfIpa.read(target);
                    return;
                } catch (Exception damaged) {
                    // Reinstall unreadable packages so they remain selectable in the manager.
                }
            }
        }
        File temp = File.createTempFile("bundled-", ".ipa", apps);
        try {
            MessageDigest sha = MessageDigest.getInstance("SHA-256");
            try (InputStream in = context.getAssets().open(BUNDLED); FileOutputStream out = new FileOutputStream(temp)) {
                copy(in, new DigestOutputStream(out, sha), 512L * 1024 * 1024);
                out.getFD().sync();
            }
            if (!hex(sha.digest()).equals(expected)) throw new IOException("内置 IPA 校验失败");
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
            if (!hasIpaExtension(file.getName())) continue;
            try { result.add(ZfIpa.read(file)); } catch (Exception ignored) { /* never offer a damaged IPA */ }
        }
        Collections.sort(result, (left, right) -> {
            int bundledFirst = Boolean.compare(!left.file.getName().equals(BUNDLED),
                !right.file.getName().equals(BUNDLED));
            return bundledFirst == 0 ? left.name.compareTo(right.name) : bundledFirst;
        });
        return result;
    }
    private static boolean hasIpaExtension(String name) {
        return name.toLowerCase(Locale.ROOT).endsWith(".ipa");
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
            if (!hasIpaExtension(safeName)) safeName += ".ipa";
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
            if (value.length() > 12 || !value.matches("[0-9]+(\\.[0-9]+)?|[0-9]+/[0-9]+"))
                throw new NumberFormatException();
            int slash = value.indexOf('/'), dot = value.indexOf('.');
            long numerator, denominator = 1;
            if (slash >= 0) {
                numerator = Long.parseLong(value.substring(0, slash));
                denominator = Long.parseLong(value.substring(slash + 1));
                if (denominator == 0 || denominator > 10000 || numerator > 10000)
                    throw new NumberFormatException();
            } else if (dot >= 0) {
                numerator = Long.parseLong(value.substring(0, dot) + value.substring(dot + 1));
                for (int digit = dot + 1; digit < value.length(); digit++) denominator *= 10;
            } else {
                numerator = Long.parseLong(value);
            }
            if (numerator < denominator || numerator > 6 * denominator)
                throw new NumberFormatException();
            // The emulator requires both parts of the reduced fraction to fit in a u32.
            long divisor = gcd(numerator, denominator);
            if (numerator / divisor > 0xffffffffL || denominator / divisor > 0xffffffffL)
                throw new NumberFormatException();
            return (double) numerator / denominator;
        } catch (NumberFormatException e) { throw new IllegalArgumentException("倍率请填 1～6 的小数或分数，例如 4、4.5、9/2"); }
    }
    private static long gcd(long left, long right) {
        while (right != 0) {
            long remainder = left % right;
            left = right;
            right = remainder;
        }
        return left;
    }
    static String validScaleOrDefault(String value) {
        try {
            scale(value);
            return value;
        } catch (IllegalArgumentException invalid) {
            return DEFAULT_SCALE;
        }
    }
    private static void validate(JSONObject app) throws Exception {
        if (!Arrays.asList("iphone", "ipad").contains(app.optString("family", DEFAULT_FAMILY)))
            throw new IllegalArgumentException("设备类型无效");
        scale(app.optString("scale", DEFAULT_SCALE));
        String fps = app.optString("fps", "60");
        if (!fps.equals("off")) {
            int number = Integer.parseInt(fps);
            if (number < 1 || number > 1000) throw new IllegalArgumentException("帧率请填 1～1000");
        }
        if (app.optLong("offset", 0) < 0) throw new IllegalArgumentException("累计跳过时间无效");
    }
    public long advance(String id, long seconds) throws Exception {
        return advance(id, seconds, settings(id));
    }
    long advance(String id, long seconds, JSONObject app) throws Exception {
        long before = app.optLong("offset", 0);
        if (seconds < 0 || before < 0 || seconds > Long.MAX_VALUE - before
                || seconds + before > MAX_GAME_EPOCH - System.currentTimeMillis() / 1000)
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
        Collections.sort(result, (left, right) -> right.getName().compareTo(left.getName()));
        return result;
    }
    public File backup(String id, String kind) throws Exception {
        File save = live(id);
        if (!save.isFile()) throw new IOException("还没有存档，请先进入游戏创建存档");
        if (save.length() > MAX_SAVE_BYTES) throw new IOException("存档大小超出限制");
        String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss-SSS", Locale.ROOT).format(new Date());
        File target = new File(backupDir(id), stamp + "_" + kind + "_" + UUID.randomUUID().toString().substring(0, 4) + ".zip");
        File temp = new File(target.getPath() + ".tmp");
        try {
            try (FileOutputStream file = new FileOutputStream(temp); ZipOutputStream zip = new ZipOutputStream(file)) {
                JSONObject metadata = new JSONObject().put("format", 1).put("appId", id)
                    .put("offset", settings(id).optLong("offset", 0));
                zip.putNextEntry(new ZipEntry("zf_backup.json"));
                zip.write(metadata.toString().getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
                zipDirectory(zip, sandbox(id), "sandbox/", new BackupLimits());
                zip.finish();
                file.getFD().sync();
            }
            if (temp.length() > MAX_BACKUP_ARCHIVE_BYTES) throw new IOException("备份文件大小超出限制");
            android.system.Os.rename(temp.getPath(), target.getPath()); return target;
        } finally { temp.delete(); }
    }
    private static final class BackupLimits {
        // The writer and reader both include the metadata entry in this limit.
        private int entries = 1;
        private long remaining = MAX_BACKUP_DATA_BYTES;

        void nextEntry() throws IOException {
            if (++entries > MAX_BACKUP_ENTRIES) throw new IOException("备份包含过多文件");
        }
        void copyData(InputStream input, OutputStream output) throws IOException {
            remaining -= copy(input, output, remaining);
        }
    }
    private static void zipDirectory(ZipOutputStream zip, File dir, String prefix, BackupLimits limits) throws IOException {
        File[] children = dir.listFiles();
        if (children == null) throw new IOException("无法读取存档目录");
        for (File child : children) {
            if (!child.getCanonicalFile().getParentFile().equals(dir.getCanonicalFile())) throw new IOException("存档路径无效");
            if (child.isDirectory()) zipDirectory(zip, child, prefix + child.getName() + "/", limits);
            else {
                limits.nextEntry();
                zip.putNextEntry(new ZipEntry(prefix + child.getName()));
                try (InputStream in = new FileInputStream(child)) { limits.copyData(in, zip); }
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
        byte[] imported = ZfIpa.readLimited(in, MAX_SAVE_BYTES); ZfSave.read(imported);
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
        File old = new File(sandbox(id).getPath() + ".before-restore-" + UUID.randomUUID());
        JSONObject oldSettings = settings(id);
        boolean moved = false, installed = false, committed = false;
        mkdir(stage);
        try {
            JSONObject metadata = null;
            Set<String> names = new HashSet<>();
            BackupLimits limits = new BackupLimits();
            try (ZipInputStream zip = new ZipInputStream(input)) {
                ZipEntry entry;
                while ((entry = zip.getNextEntry()) != null) {
                    String name = entry.getName();
                    if (!names.add(name) || name.contains("\\")) throw new IOException("备份目录无效");
                    if (name.equals("zf_backup.json")) {
                        metadata = new JSONObject(new String(ZfIpa.readLimited(zip, MAX_BACKUP_METADATA_BYTES), StandardCharsets.UTF_8));
                    } else {
                        limits.nextEntry();
                        if (!name.startsWith("sandbox/")) throw new IOException("备份包含未知文件");
                        File target = new File(stage, name);
                        if (!target.getCanonicalPath().startsWith(incoming.getCanonicalPath() + File.separator))
                            throw new IOException("备份包含越界路径");
                        if (entry.isDirectory()) {
                            if (zip.read() != -1) throw new IOException("备份目录包含数据");
                            mkdir(target);
                        } else {
                            mkdir(target.getParentFile());
                            try (FileOutputStream out = new FileOutputStream(target)) {
                                limits.copyData(zip, out);
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
            if (offset < 0 || offset > MAX_GAME_EPOCH - System.currentTimeMillis() / 1000)
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
            committed = true;
        } catch (Exception e) {
            try {
                if (installed) android.system.Os.rename(sandbox(id).getPath(), incoming.getPath());
                if (moved) android.system.Os.rename(old.getPath(), sandbox(id).getPath());
            } catch (Exception rollback) {
                e.addSuppressed(rollback);
                throw new IOException("恢复失败，原存档保留在 " + old.getName(), e);
            }
            throw e;
        } finally {
            cleanupRestoreDirectory(stage);
            if (committed) cleanupRestoreDirectory(old);
        }
    }
    private static void cleanupRestoreDirectory(File directory) {
        try { deleteTree(directory); }
        catch (IOException e) { Log.w("ZfStorage", "Unable to remove restore directory " + directory, e); }
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
