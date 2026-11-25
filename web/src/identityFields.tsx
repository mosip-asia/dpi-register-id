const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const detailFields = [
  "fullName",
  "dateOfBirth",
  "gender",
  "email",
  "phone",
  "referenceIdentityNumber",
] as const;

export const addressFields = [
  "addressLine1",
  "addressLine2",
  "addressLine3",
  "city",
  "zone",
  "province",
  "region",
  "postalCode",
] as const;

export const citizenFields = [...detailFields, ...addressFields] as const;

export type DetailField = (typeof detailFields)[number];
export type AddressField = (typeof addressFields)[number];
export type CitizenField = (typeof citizenFields)[number];

type FieldMeta = {
  label: string;
  optional: boolean;
  input: "text" | "email" | "tel" | "date";
  autoComplete?: string;
  maxLength?: number;
};

export const fieldMeta: Record<CitizenField, FieldMeta> = {
  fullName: { label: "Full name", optional: false, input: "text", autoComplete: "name", maxLength: 128 },
  dateOfBirth: { label: "Date of birth", optional: false, input: "date", autoComplete: "bday" },
  gender: { label: "Gender", optional: false, input: "text" },
  email: { label: "Email", optional: false, input: "email", autoComplete: "email", maxLength: 128 },
  phone: { label: "Phone number", optional: false, input: "tel", autoComplete: "tel", maxLength: 32 },
  referenceIdentityNumber: {
    label: "Reference ID number",
    optional: false,
    input: "text",
    maxLength: 64,
  },
  addressLine1: {
    label: "Address line 1",
    optional: false,
    input: "text",
    autoComplete: "address-line1",
    maxLength: 128,
  },
  addressLine2: {
    label: "Address line 2",
    optional: true,
    input: "text",
    autoComplete: "address-line2",
    maxLength: 128,
  },
  addressLine3: {
    label: "Address line 3",
    optional: true,
    input: "text",
    autoComplete: "address-line3",
    maxLength: 128,
  },
  city: { label: "City", optional: false, input: "text", autoComplete: "address-level2", maxLength: 64 },
  zone: { label: "Zone / township", optional: false, input: "text", maxLength: 32 },
  province: { label: "Province / state", optional: false, input: "text", autoComplete: "address-level1", maxLength: 64 },
  region: { label: "Region", optional: false, input: "text", maxLength: 64 },
  postalCode: { label: "Postal code", optional: false, input: "text", autoComplete: "postal-code", maxLength: 16 },
};

const genders = ["Female", "Male", "Another", "Prefer not to say"] as const;

export function isCitizenField(value: string): value is CitizenField {
  return (citizenFields as readonly string[]).includes(value);
}

export function filled(value: string) {
  return value.trim() !== "";
}

export function emailInvalid(email: string) {
  const trimmed = email.trim();
  return trimmed !== "" && !EMAIL.test(trimmed);
}

export function emailOk(email: string) {
  return filled(email) && !emailInvalid(email);
}

export function fieldOk(field: CitizenField, value: string) {
  if (field === "email") return emailOk(value);
  if (fieldMeta[field].optional) return true;
  return filled(value);
}

export function detailsReady(flow: Record<DetailField, string>) {
  return detailFields.every((field) => fieldOk(field, flow[field]));
}

export function addressReady(flow: Record<AddressField, string>) {
  return addressFields.every((field) => fieldOk(field, flow[field]));
}

export function identityReady(flow: Record<CitizenField, string>) {
  return detailsReady(flow) && addressReady(flow);
}

export function displayValue(field: CitizenField, value: string) {
  const trimmed = value.trim();
  if (trimmed) return trimmed;
  if (fieldMeta[field].optional) return "Left blank";
  return "Missing";
}

export function IdentityField({
  field,
  value,
  onChange,
}: {
  field: CitizenField;
  value: string;
  onChange: (value: string) => void;
}) {
  const meta = fieldMeta[field];
  const invalid = field === "email" && emailInvalid(value);
  const label = meta.optional ? `${meta.label} (optional)` : meta.label;

  return (
    <label htmlFor={`field-${field}`}>
      {label}
      {field === "gender" ? (
        <select id={`field-${field}`} value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Select</option>
          {genders.map((gender) => (
            <option key={gender}>{gender}</option>
          ))}
        </select>
      ) : (
        <input
          id={`field-${field}`}
          type={meta.input}
          value={value}
          autoComplete={meta.autoComplete}
          maxLength={meta.maxLength}
          aria-invalid={invalid || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}
