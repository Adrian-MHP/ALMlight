import { useState } from "react";
import { Select } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useItems } from "@/api/hooks";
import { useProjectCtx } from "@/pages/project/ProjectLayout";

interface Props {
  label?: string;
  placeholder?: string;
  value: string | null;
  onChange: (key: string | null) => void;
  types?: string[];
  exclude?: string[];
  required?: boolean;
  description?: string;
  testId?: string;
}

/** Searchable item selector (by key or title) limited to the given item types. */
export function ItemPicker({ label, placeholder = "Search by key or title…", value, onChange, types, exclude = [], required,
  description, testId }: Props) {
  const { key } = useProjectCtx();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 250);
  const { data } = useItems(key, { q: debounced || undefined, type: types, limit: 30, sort: "key" });
  const options = (data?.items ?? [])
    .filter((i) => !exclude.includes(i.key))
    .map((i) => ({ value: i.key, label: `${i.key} — ${i.title}` }));
  if (value && !options.some((o) => o.value === value)) options.unshift({ value, label: value });
  return (
    <Select label={label} placeholder={placeholder} data={options} value={value} onChange={onChange} searchable
      searchValue={search} onSearchChange={setSearch} filter={({ options }) => options} clearable required={required}
      description={description} nothingFoundMessage="No matching items" data-testid={testId} />
  );
}
