import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Text } from "@mantine/core";

/** Renders Markdown descriptions. Raw HTML is not rendered (react-markdown default), so content is XSS-safe. */
export function Markdown({ text, empty = "No description." }: { text: string | null | undefined; empty?: string }) {
  if (!text?.trim()) return <Text c="dimmed" size="sm" fs="italic">{empty}</Text>;
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
