export const PASSWORD_MIN_CODE_POINTS = 12;
export const PASSWORD_MAX_CODE_POINTS = 128;
export const PASSWORD_SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{}:,.?";

export type PasswordRequirement =
  | "length"
  | "uppercase"
  | "lowercase"
  | "digit"
  | "special";

export type PasswordPolicyResult = {
  valid: boolean;
  unmetRequirements: PasswordRequirement[];
};

export const PASSWORD_REQUIREMENTS: readonly PasswordRequirement[] = [
  "length",
  "uppercase",
  "lowercase",
  "digit",
  "special"
];

export function evaluatePasswordPolicy(
  password: string
): PasswordPolicyResult {
  const codePointLength = [...password].length;
  const satisfied: Record<PasswordRequirement, boolean> = {
    length:
      codePointLength >= PASSWORD_MIN_CODE_POINTS &&
      codePointLength <= PASSWORD_MAX_CODE_POINTS,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    digit: /[0-9]/.test(password),
    special: [...password].some((character) =>
      PASSWORD_SPECIAL_CHARACTERS.includes(character)
    )
  };
  const unmetRequirements = PASSWORD_REQUIREMENTS.filter(
    (requirement) => !satisfied[requirement]
  );

  return {
    valid: unmetRequirements.length === 0,
    unmetRequirements
  };
}
