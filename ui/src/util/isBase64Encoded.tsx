// This regEx detects RFC 2047 encoded-words in email headers.
// Example: =?utf-8?B?Ag==?= or =?UTF-8?Q?Jane=E2=80=99s?=
//
// We use `[^?]+` (not `.+`) for charset and encoded text because RFC 2047
// forbids `?` in those fields, and a greedy `.+` would span across two
// adjacent encoded-words and capture e.g. `UTF-8?Q?…?= =?UTF-8` as the
// charset, which then crashes the TextDecoder.
export const RE_ENCODED_HEADER = new RegExp("=\\?([^?]+)\\?([BQ])\\?([^?]+)\\?=");

// Global variant for iterative decoding across all encoded-words in a
// single string. Kept separate so `RE_ENCODED_HEADER.test()` and
// `String.prototype.match()` callers don't see `lastIndex` state leaks.
const RE_ENCODED_HEADER_GLOBAL = new RegExp(
  "=\\?([^?]+)\\?([BQ])\\?([^?]+)\\?=",
  "g"
);

function decodeWord(charset: string, encoding: string, payload: string): string {
  let bytes: Uint8Array;
  if (encoding.toUpperCase() === "B") {
    const binaryStr = atob(payload);
    bytes = Uint8Array.from(binaryStr, (c) => c.charCodeAt(0));
  } else {
    // Quoted-Printable: `_` is space, `=XX` is a hex byte.
    const qpDecoded = payload
      .replace(/_/g, " ")
      .replace(/=([A-Fa-f0-9]{2})/g, (_, hex) =>
        String.fromCharCode(parseInt(hex, 16))
      );
    bytes = Uint8Array.from(qpDecoded, (c) => c.charCodeAt(0));
  }
  try {
    return new TextDecoder(charset).decode(bytes);
  } catch {
    // Unknown charset — fall back to utf-8 rather than crashing the render.
    return new TextDecoder().decode(bytes);
  }
}

// Decodes every RFC 2047 encoded-word in `input`. Per RFC 2047, whitespace
// between adjacent encoded-words is purely for line-folding and must be
// dropped when joining the decoded content.
export function decodeMimeHeader(input: string): string {
  if (!RE_ENCODED_HEADER.test(input)) {
    return input;
  }
  // Collapse whitespace between adjacent encoded-words first, so
  // "=?..?= =?..?=" decodes as a single concatenated string.
  const collapsed = input.replace(/\?=\s+=\?/g, "?==?");
  return collapsed.replace(
    RE_ENCODED_HEADER_GLOBAL,
    (_match, charset, encoding, payload) =>
      decodeWord(charset, encoding, payload)
  );
}
