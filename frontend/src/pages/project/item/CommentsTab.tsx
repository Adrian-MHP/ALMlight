import { useThreads } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { CommentThreads } from "@/components/CommentThreads";
import { useProjectCtx } from "../ProjectLayout";

export function CommentsTab({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const threads = useThreads(key, item.key).data ?? [];
  return <CommentThreads projectKey={key} threads={threads} itemKey={item.key} canWrite={can("contributor")} canModerate={can("manager")} />;
}
