import { useMemo, useRef, useState } from "react";
import { Paper, Textarea, UnstyledButton, Text, type TextareaProps } from "@mantine/core";
import { useDirectory } from "@/api/hooks";

/** Textarea with "@" suggestions of users; inserts @username (the user is notified when the comment is saved). */
export function MentionTextarea({ value, onChange, ...rest }: Omit<TextareaProps, "onChange" | "value"> & {
  value: string; onChange: (v: string) => void;
}) {
  const users = useDirectory().data ?? [];
  const ref = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState<{ text: string; start: number } | null>(null);
  const matches = useMemo(() => {
    if (!query) return [];
    const q = query.text.toLowerCase();
    return users.filter((u) => u.username?.toLowerCase().startsWith(q) || u.display_name.toLowerCase().includes(q)).slice(0, 6);
  }, [query, users]);

  function detect(text: string, caret: number) {
    const before = text.slice(0, caret);
    const m = /(^|[\s(])@([A-Za-z0-9_.-]{0,30})$/.exec(before);
    setQuery(m ? { text: m[2], start: caret - m[2].length - 1 } : null);
  }
  function pick(username: string) {
    if (!query || !ref.current) return;
    const caret = ref.current.selectionStart ?? value.length;
    const next = `${value.slice(0, query.start)}@${username} ${value.slice(caret)}`;
    onChange(next);
    setQuery(null);
    requestAnimationFrame(() => {
      const pos = query.start + username.length + 2;
      ref.current?.focus();
      ref.current?.setSelectionRange(pos, pos);
    });
  }
  return (
    <div style={{ position: "relative" }}>
      <Textarea {...rest} ref={ref} value={value}
        onChange={(e) => { onChange(e.currentTarget.value); detect(e.currentTarget.value, e.currentTarget.selectionStart ?? 0); }}
        onKeyDown={(e) => { if (query && matches.length && (e.key === "Enter" || e.key === "Tab")) { e.preventDefault(); pick(matches[0].username!); } if (e.key === "Escape") setQuery(null); }}
        onBlur={() => setTimeout(() => setQuery(null), 150)} />
      {query && matches.length > 0 && (
        <Paper withBorder shadow="md" p={4} className="mention-list" data-testid="mention-list">
          {matches.map((u) => (
            <UnstyledButton key={u.id} className="item-suggest-row" onMouseDown={(e) => { e.preventDefault(); pick(u.username!); }}
              data-testid={`mention-${u.username}`}>
              <Text size="sm" fw={600}>@{u.username}</Text><Text size="sm" c="dimmed">{u.display_name}</Text>
            </UnstyledButton>
          ))}
        </Paper>
      )}
    </div>
  );
}

/** Highlight @mentions in Markdown comment text. */
export function emphasizeMentions(text: string): string {
  return text.replace(/(^|[\s(])@([A-Za-z0-9_.-]{2,64}(?:@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)?)/g, "$1**@$2**");
}
