/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.*;
import org.xml.sax.InputSource;

/** Reads IPA metadata without extracting executable content. */
public final class ZfIpa {
    public final File file;
    public final String appId, version, name;
    private ZfIpa(File file, String appId, String version) {
        this.file = file; this.appId = appId; this.version = version;
        this.name = file.getName().equals("Zombie_Farm_v29fix.ipa")
            ? "内置中文版 · v29fix" : file.getName().replaceFirst("^[0-9a-f]{12}_", "");
    }
    @Override public String toString() { return name; }

    public static ZfIpa read(File file) throws Exception {
        try (ZipFile zip = new ZipFile(file)) {
            ZipEntry info = null;
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                if (entry.getName().matches("Payload/[^/]+\\.app/Info\\.plist")) {
                    if (info != null) throw new IOException("IPA 包含多个应用");
                    info = entry;
                }
            }
            if (info == null) throw new IOException("IPA 缺少 Info.plist");
            byte[] data;
            try (InputStream in = zip.getInputStream(info)) { data = readLimited(in, 1024 * 1024); }
            Map<String, Object> values = plist(data);
            String id = string(values.get("CFBundleIdentifier"));
            if (!Arrays.asList("com.playforge.ZombieFarm.ZFR", "com.playforge.ZombieFarmChinese",
                    "com.playforge.ZFR.LZ54D2GT3D").contains(id))
                throw new IOException("请选择 Zombie Farm 的 IPA，当前应用为 " + id);
            String executable = string(values.get("CFBundleExecutable"));
            if (executable.isEmpty() || executable.contains("/") || executable.contains("\\")
                    || zip.getEntry(info.getName().replace("Info.plist", executable)) == null)
                throw new IOException("IPA 缺少游戏执行文件");
            String version = string(values.get("CFBundleShortVersionString"));
            if (version.isEmpty()) version = string(values.get("CFBundleVersion"));
            return new ZfIpa(file, id, version);
        }
    }

    private static String string(Object value) { return value instanceof String ? (String)value : ""; }
    public static byte[] readLimited(InputStream in, int maximum) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) != -1) {
            if ((long)out.size() + n > maximum) throw new IOException("文件大小超出限制");
            out.write(buffer, 0, n);
        }
        return out.toByteArray();
    }

    private static Map<String, Object> plist(byte[] data) throws Exception {
        if (data.length >= 8 && new String(data, 0, 8, StandardCharsets.US_ASCII).equals("bplist00"))
            return new BinaryPlist(data).dictionary();
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        // Android's parser does not support the desktop Xerces feature flags.
        // Reject internal entity definitions and resolve external DTDs locally.
        if (java.util.regex.Pattern.compile("<!\\s*ENTITY", java.util.regex.Pattern.CASE_INSENSITIVE)
                .matcher(new String(data, StandardCharsets.UTF_8)).find())
            throw new IOException("Info.plist 包含不支持的实体定义");
        factory.setExpandEntityReferences(false);
        javax.xml.parsers.DocumentBuilder builder = factory.newDocumentBuilder();
        builder.setEntityResolver((publicId, systemId) -> new InputSource(new StringReader("")));
        Document document = builder.parse(new ByteArrayInputStream(data));
        NodeList dicts = document.getElementsByTagName("dict");
        if (dicts.getLength() == 0) throw new IOException("Info.plist 格式无效");
        Map<String, Object> result = new HashMap<>(); String key = null;
        for (Node node = dicts.item(0).getFirstChild(); node != null; node = node.getNextSibling()) {
            if (node.getNodeType() != Node.ELEMENT_NODE) continue;
            if (node.getNodeName().equals("key")) key = node.getTextContent();
            else if (key != null) { result.put(key, node.getTextContent()); key = null; }
        }
        return result;
    }

    private static final class BinaryPlist {
        final byte[] data; final int referenceSize; final long[] offsets; final int root;
        BinaryPlist(byte[] data) throws IOException {
            this.data = data;
            if (data.length < 40) throw new IOException("plist 不完整");
            int trailer = data.length - 32;
            int offsetSize = data[trailer + 6] & 255;
            referenceSize = data[trailer + 7] & 255;
            long count = integer(trailer + 8, 8), top = integer(trailer + 16, 8);
            long table = integer(trailer + 24, 8);
            if (offsetSize < 1 || offsetSize > 8 || referenceSize < 1 || referenceSize > 8
                    || count < 1 || count > 100000 || top < 0 || top >= count
                    || table < 8 || table + count * offsetSize > trailer)
                throw new IOException("plist 索引无效");
            root = (int)top; offsets = new long[(int)count];
            for (int i = 0; i < count; i++) offsets[i] = integer((int)table + i * offsetSize, offsetSize);
        }
        long integer(int pos, int size) throws IOException {
            if (size < 1 || size > 8 || pos < 0 || (long)pos + size > data.length)
                throw new IOException("plist 越界");
            long result = 0;
            for (int i = 0; i < size; i++) result = (result << 8) | (data[pos + i] & 255);
            return result;
        }
        Object object(int index, int depth) throws IOException {
            if (depth > 12 || index < 0 || index >= offsets.length || offsets[index] < 8
                    || offsets[index] >= data.length - 32) throw new IOException("plist 对象无效");
            int pos = (int)offsets[index], marker = data[pos++] & 255;
            int type = marker >> 4, count = marker & 15;
            if (type != 5 && type != 6 && type != 13) return null;
            if (count == 15) {
                if (pos >= data.length || (data[pos] & 0xf0) != 0x10)
                    throw new IOException("plist 长度无效");
                int power = data[pos++] & 15;
                if (power > 3) throw new IOException("plist 长度过大");
                int size = 1 << power;
                long length = integer(pos, size); pos += size;
                if (length < 0 || length > 1000000) throw new IOException("plist 长度过大");
                count = (int)length;
            }
            long bytes = (long)count * (type == 6 ? 2 : type == 13 ? referenceSize * 2 : 1);
            if ((long)pos + bytes > data.length - 32) throw new IOException("plist 数据越界");
            if (type == 5) return new String(data, pos, count, StandardCharsets.US_ASCII);
            if (type == 6) return new String(data, pos, count * 2, StandardCharsets.UTF_16BE);
            Map<String, Object> result = new HashMap<>();
            for (int i = 0; i < count; i++) {
                long kr = integer(pos + i * referenceSize, referenceSize);
                long vr = integer(pos + (count + i) * referenceSize, referenceSize);
                if (kr > Integer.MAX_VALUE || vr > Integer.MAX_VALUE) throw new IOException("plist 引用无效");
                Object key = object((int)kr, depth + 1);
                if (key instanceof String) result.put((String)key, object((int)vr, depth + 1));
            }
            return result;
        }
        @SuppressWarnings("unchecked") Map<String, Object> dictionary() throws IOException {
            Object result = object(root, 0);
            if (!(result instanceof Map)) throw new IOException("plist 根对象不是字典");
            return (Map<String, Object>)result;
        }
    }
}
