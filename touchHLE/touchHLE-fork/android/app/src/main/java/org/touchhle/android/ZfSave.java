/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.BufferUnderflowException;
import java.util.Arrays;

/** The same validated version-14 currency layout used by GameManager.ps1. */
public final class ZfSave {
    private static final byte[] MARKER = {
        1, 9, 0, 0, 0, 0x55, 0x4e, 0x44, 0x45, 0x46, 0x49, 0x4e, 0x45, 0x44
    };
    public final int gold, brains, marker;

    private ZfSave(int gold, int brains, int marker) {
        this.gold = gold; this.brains = brains; this.marker = marker;
    }

    public static ZfSave read(String appId, byte[] bytes) {
        ByteBuffer b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        if (bytes.length < 4 || b.getInt(0) != 14)
            throw new IllegalArgumentException("这不是受支持的版本 14 存档");
        int found = -1;
        for (int i = 0; i <= bytes.length - MARKER.length; i++) {
            boolean matches = true;
            for (int j = 0; j < MARKER.length; j++)
                if (bytes[i + j] != MARKER[j]) { matches = false; break; }
            if (matches) {
                if (found >= 0) throw new IllegalArgumentException("存档有多个玩家数据块");
                found = i;
            }
        }
        if (found < 0 || bytes.length < found + 0x5e)
            throw new IllegalArgumentException("玩家数据块缺失或不完整");
        int gold = b.getInt(found + 0x46), brains = b.getInt(found + 0x4a);
        if (b.getInt(found + 0x42) != 4 || b.getInt(found + 0x52) != 0 || gold < 0 || brains < 0)
            throw new IllegalArgumentException("玩家数据块校验失败，存档未被修改");
        b.position(found + 0x56);
        if ("com.playforge.ZombieFarm.ZFR".equals(appId)) {
            validateQuests(b);
        } else {
            int first = b.getInt(), second = b.getInt();
            if (first < 0 || first > 1000000 || second < 0 || second > 1000000)
                throw new IllegalArgumentException("玩家数据块校验失败，存档未被修改");
        }
        return new ZfSave(gold, brains, found);
    }

    private static void skipQuestWords(ByteBuffer b) {
        int count = b.getInt();
        if (count < 0 || count > b.remaining() / 4)
            throw new IllegalArgumentException("任务列表缺失或不完整");
        b.position(b.position() + count * 4);
    }

    private static void validateQuests(ByteBuffer b) {
        try {
            skipQuestWords(b); // completed quest IDs
            int active = b.getInt();
            if (active < 0 || active > b.remaining() / 8)
                throw new IllegalArgumentException("活动任务列表缺失或不完整");
            for (int i = 0; i < active; i++) {
                b.getInt(); // quest ID
                skipQuestWords(b); // progress values
            }
        } catch (BufferUnderflowException e) {
            throw new IllegalArgumentException("任务数据缺失或不完整", e);
        }
    }

    public static byte[] edit(String appId, byte[] original, int gold, int brains) {
        if (gold < 0 || brains < 0) throw new IllegalArgumentException("金币和脑子不能为负数");
        ZfSave layout = read(appId, original);
        byte[] updated = Arrays.copyOf(original, original.length);
        ByteBuffer b = ByteBuffer.wrap(updated).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(layout.marker + 0x46, gold);
        b.putInt(layout.marker + 0x4a, brains);
        ZfSave check = read(appId, updated);
        if (check.gold != gold || check.brains != brains || check.marker != layout.marker)
            throw new IllegalArgumentException("货币写入校验失败");
        return updated;
    }
}
