// Usage: npm run hash-password            (prompts; input is not echoed)
// Prints a scrypt hash to paste into CC_USERS. The password itself is never written anywhere.
import { randomBytes, scryptSync } from "node:crypto";
import readline from "node:readline";

const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
rl._writeToOutput = (s) => {
  if (s.includes("パスワード")) rl.output.write(s);
};
rl.question("パスワード: ", (pw) => {
  rl.close();
  process.stdout.write("\n");
  if (!pw || pw.length < 12) {
    console.error("12文字以上にしてください");
    process.exit(1);
  }
  const salt = randomBytes(16);
  const hash = scryptSync(pw, salt, 32, { N: 16384, r: 8, p: 1 });
  console.log(["scrypt", salt.toString("base64"), hash.toString("base64")].join("$"));
});
