type Props = {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  id: string;
  disabled?: boolean;
};

export function MoneyField({ label, value, onChange, error, id, disabled }: Props) {
  return (
    <div className={`field${error ? " has-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-err` : undefined}
        placeholder="0.00"
      />
      {error ? (
        <span className="field-error" id={`${id}-err`} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
