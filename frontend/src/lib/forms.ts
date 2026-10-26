/** Browsers and password managers offer the saved site login for a text field followed by a password field.
 *  Fields that hold a *foreign* credential (an access token of a Git or SysML server) must not be filled with the
 *  Ariadne account: a wrong token makes even a public repository answer "no access". Spread this on both fields. */
export const NO_FILL = {
  autoComplete: "off",
  "data-lpignore": "true",
  "data-1p-ignore": "true",
  "data-bwignore": "true",
} as const;
