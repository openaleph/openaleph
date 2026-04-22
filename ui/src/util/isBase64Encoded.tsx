// this regEx detects E-Mail headers that are encoded
// example: =?utf-8?B?Ag==?=
export const RE_ENCODED_HEADER = new RegExp("=\\?(.+)\\?([BQ])\\?(.+)\\?=");
