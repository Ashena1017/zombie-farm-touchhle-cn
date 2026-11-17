"""Run the real Android scale parser with the bundled JDK, without device data."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '_analysis/dumps/farmer-scroll-20261117'
SOURCE = ROOT / 'touchHLE/touchHLE-fork/android/app/src/main/java/org/touchhle/android/ZfStorage.java'


def main():
    text = SOURCE.read_text(encoding='utf-8')
    start = text.index('public static double scale(')
    opening = text.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    source = '''public class ScaleTest {
    // PRODUCTION
    public static void main(String[] args) {
        for (String value : new String[]{"1", "3", "4", "5", "6", "4.5", "9/2", "12/2"}) {
            double got = scale(value);
            if (got < 1 || got > 6) throw new AssertionError(value);
        }
        if (scale("4.5") != scale("9/2") || scale("6") != 6) throw new AssertionError("roundtrip");
        for (String value : new String[]{"0", "0.99", "6.01", "13/2", "1/0", "NaN", "Infinity", "3//2", "7"}) {
            boolean refused = false;
            try { scale(value); } catch (IllegalArgumentException expected) { refused = true; }
            if (!refused) throw new AssertionError("accepted " + value);
        }
        System.out.println("PASS: Android scale parser, 8 valid / 9 invalid values, decimal and fraction equivalence");
    }
}'''.replace('// PRODUCTION', text[start:end])
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'ScaleTest.java'
    path.write_text(source, encoding='utf-8')
    jdk = Path('C:/Users/Loner/AppData/Local/Temp/zfr-android-toolchain/jdk17/bin')
    subprocess.run([str(jdk / 'javac.exe'), '-encoding', 'UTF-8', str(path)], check=True)
    result = subprocess.run([str(jdk / 'java.exe'), '-cp', str(OUT), 'ScaleTest'], capture_output=True, text=True, check=True)
    (OUT / 'android-scale-tests.txt').write_text(result.stdout, encoding='utf-8')
    print(result.stdout)


if __name__ == '__main__':
    main()
