// Add a location: a country (dropdown) and, optionally, a state or city in it. Gives
// "Karnataka, India" or "India": the country becomes JSearch's country parameter and the whole
// text goes into the query ("AI Engineer in Karnataka, India").
import { useEffect, useId, useState } from "react";
import { Plus } from "lucide-react";
import { api } from "../../lib/api";
import type { CountryOption } from "../../lib/types";
import { Button, Input } from "../ui";
import { Select } from "../settings/form";

let cache: CountryOption[] | null = null;

export function LocationAdd({ onAdd, existing = [], defaultCountry = "IN" }: { onAdd: (place: string) => void; existing?: string[]; defaultCountry?: string }) {
  const [countries, setCountries] = useState<CountryOption[] | null>(cache);
  const [code, setCode] = useState(defaultCountry);
  const [place, setPlace] = useState("");
  const listId = useId();

  useEffect(() => {
    if (cache) return;
    void api.listPlaces().then((c) => {
      cache = c;
      setCountries(c);
    });
  }, []);

  const country = countries?.find((c) => c.code === code);
  const value = country ? (place.trim() ? `${place.trim()}, ${country.name}` : country.name) : "";
  const dup = existing.some((x) => x.toLowerCase() === value.toLowerCase());

  const add = () => {
    if (!value || dup) return;
    onAdd(value);
    setPlace("");
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select aria-label="Country" value={code} onChange={(e) => setCode(e.target.value)} className="w-44" disabled={!countries}>
        {(countries ?? []).map((c) => (
          <option key={c.code} value={c.code}>
            {c.name}
          </option>
        ))}
      </Select>
      <Input
        aria-label="State or city (optional)"
        list={listId}
        value={place}
        onChange={(e) => setPlace(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        placeholder="State or city (optional)"
        className="min-w-40 flex-1"
      />
      <datalist id={listId}>
        {(country?.places ?? []).map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
      <Button size="sm" icon={<Plus className="size-4" />} disabled={!value || dup} onClick={add}>
        {dup ? "Added" : "Add"}
      </Button>
    </div>
  );
}
