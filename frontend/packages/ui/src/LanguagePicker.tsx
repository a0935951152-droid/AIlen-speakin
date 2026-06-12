/** 語言選擇器：選項來自設定（語言數是設定值不是結構，§6.3）。 */

const LABELS: Record<string, string> = { zh: "中文", en: "English", ja: "日本語" };

export function LanguagePicker({ langs, value, onChange }: {
  langs: string[];
  value: string;
  onChange: (lang: string) => void;
}) {
  return (
    <select className="lang-picker" value={value} onChange={(e) => onChange(e.target.value)}>
      {langs.map((l) => (
        <option key={l} value={l}>{LABELS[l] ?? l}</option>
      ))}
    </select>
  );
}
