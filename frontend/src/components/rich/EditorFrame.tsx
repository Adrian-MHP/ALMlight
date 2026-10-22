import type { ReactNode } from "react";
import { RichTextEditor } from "@mantine/tiptap";
import { useEditorState, type Editor } from "@tiptap/react";
import { notifications } from "@mantine/notifications";
import { api } from "@/api/client";

/** Uploads an image for rich text and returns its URL in the content-addressed image store. */
export function uploadImage(projectKey: string) {
  return async (file: File): Promise<string> => {
    const form = new FormData();
    form.append("file", file);
    const res = await api.upload<{ url: string }>(`/projects/${projectKey}/images`, form);
    return res.url;
  };
}

export function uploadError(_file: File, error: unknown) {
  notifications.show({ color: "red", title: "Image not added", message: error instanceof Error ? error.message : "Upload failed" });
}

/** Toolbar + content area of a rich-text editor (standalone or live). */
export function EditorFrame({ editor, onImageUpload, extra, testId, minHeight = 140, toolbar = true }: {
  editor: Editor | null; onImageUpload?: (file: File) => Promise<string>; extra?: ReactNode; testId?: string;
  minHeight?: number; toolbar?: boolean;
}) {
  const inTable = useEditorState({ editor, selector: ({ editor: e }) => !!e?.isActive("table") }) ?? false;
  return (
    <RichTextEditor editor={editor} onImageUpload={onImageUpload} onImageUploadError={uploadError} className="rte"
      data-testid={testId}>
      {toolbar && (
        <RichTextEditor.Toolbar sticky stickyOffset={0} className="rte-toolbar">
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.Bold />
            <RichTextEditor.Italic />
            <RichTextEditor.Underline />
            <RichTextEditor.Strikethrough />
            <RichTextEditor.Highlight />
            <RichTextEditor.Code />
            <RichTextEditor.ClearFormatting />
          </RichTextEditor.ControlsGroup>
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.H2 />
            <RichTextEditor.H3 />
            <RichTextEditor.H4 />
          </RichTextEditor.ControlsGroup>
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.BulletList />
            <RichTextEditor.OrderedList />
            <RichTextEditor.Blockquote />
            <RichTextEditor.CodeBlock />
            <RichTextEditor.Hr />
          </RichTextEditor.ControlsGroup>
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.Subscript />
            <RichTextEditor.Superscript />
            <RichTextEditor.Link />
            <RichTextEditor.Unlink />
          </RichTextEditor.ControlsGroup>
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.AlignLeft />
            <RichTextEditor.AlignCenter />
            <RichTextEditor.AlignRight />
          </RichTextEditor.ControlsGroup>
          <RichTextEditor.ControlsGroup>
            {onImageUpload && <RichTextEditor.ImageUpload accept="image/png,image/jpeg,image/gif,image/webp" data-testid="rte-image" />}
            <RichTextEditor.TableInsert data-testid="rte-table" />
          </RichTextEditor.ControlsGroup>
          {inTable && (
            <RichTextEditor.ControlsGroup>
              <RichTextEditor.TableRowBefore />
              <RichTextEditor.TableRowAfter />
              <RichTextEditor.TableRowDelete />
              <RichTextEditor.TableColumnBefore />
              <RichTextEditor.TableColumnAfter />
              <RichTextEditor.TableColumnDelete />
              <RichTextEditor.TableToggleHeaderRow />
              <RichTextEditor.TableMergeCells />
              <RichTextEditor.TableSplitCell />
              <RichTextEditor.TableDelete />
            </RichTextEditor.ControlsGroup>
          )}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.Undo />
            <RichTextEditor.Redo />
          </RichTextEditor.ControlsGroup>
          {extra}
        </RichTextEditor.Toolbar>
      )}
      <RichTextEditor.Content style={{ minHeight }} />
    </RichTextEditor>
  );
}
