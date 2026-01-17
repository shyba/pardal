import app.freerouting.designforms.specctra.IJFlexScanner;
import app.freerouting.designforms.specctra.Keyword;

import java.io.FileInputStream;
import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;

public final class FreeroutingSesSmoke {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("Usage: FreeroutingSesSmoke <path.dsn> <path.ses>");
            System.exit(2);
        }
        String sesPath = args[1];

        try (InputStream in = new FileInputStream(sesPath)) {
            Class<?> cls = Class.forName("app.freerouting.designforms.specctra.SpecctraDsnStreamReader");
            Constructor<?> ctor = cls.getDeclaredConstructor(InputStream.class);
            ctor.setAccessible(true);
            IJFlexScanner scanner = (IJFlexScanner) ctor.newInstance(in);

            Field nameField = cls.getDeclaredField("NAME");
            nameField.setAccessible(true);
            int NAME = nameField.getInt(null);

            Object t0 = scanner.next_token();
            Object t1 = scanner.next_token();

            if (t0 != Keyword.OPEN_BRACKET || t1 != Keyword.SESSION) {
                System.err.println("Not a Specctra SES file (missing (session ...)): " + sesPath);
                System.exit(3);
            }

            // Consume session name token (string/identifier).
            scanner.yybegin(NAME);
            Object nameTok = scanner.next_token();
            if (nameTok == null) {
                System.err.println("Unexpected EOF reading session name: " + sesPath);
                System.exit(4);
            }

            int depth = 1; // already saw the outer '('
            while (true) {
                Object tok = scanner.next_token();
                if (tok == null) {
                    break;
                }
                if (tok == Keyword.OPEN_BRACKET) {
                    depth++;
                } else if (tok == Keyword.CLOSED_BRACKET) {
                    depth--;
                    if (depth == 0) {
                        break;
                    }
                }
            }
            if (depth != 0) {
                System.err.println("Unbalanced parentheses while scanning SES: " + sesPath + " depth=" + depth);
                System.exit(5);
            }
        }
    }
}
