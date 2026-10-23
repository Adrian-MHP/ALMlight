import { useState } from "react";
import { Alert, Button, Group, Modal, PasswordInput, Stack, Text, Textarea } from "@mantine/core";
import { IconSignature } from "@tabler/icons-react";
import { tx } from "@/lib/i18n";

export interface PromptResult {
  comment: string;
  password: string;
}

/**
 * Confirmation dialog for workflow actions: optional/required comment and, for signed actions,
 * the electronic signature (password re-entry, meaning shown to the signer).
 */
export function ActionPrompt({ opened, onClose, onConfirm, title, meaning, signature, commentRequired, confirmLabel = tx("Confirm"),
  color, loading }: {
  opened: boolean;
  onClose: () => void;
  onConfirm: (r: PromptResult) => void;
  title: string;
  meaning?: string;
  signature: boolean;
  commentRequired: boolean;
  confirmLabel?: string;
  color?: string;
  loading?: boolean;
}) {
  const [comment, setComment] = useState("");
  const [password, setPassword] = useState("");
  const valid = (!commentRequired || comment.trim()) && (!signature || password);
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered>
      <form onSubmit={(e) => { e.preventDefault(); if (valid) onConfirm({ comment, password }); }}>
        <Stack>
          {meaning && <Text size="sm">{meaning}</Text>}
          <Textarea label={tx("Comment")} required={commentRequired} autosize minRows={2} value={comment}
            onChange={(e) => setComment(e.currentTarget.value)} data-testid="prompt-comment" />
          {signature && (
            <>
              <Alert icon={<IconSignature size={16} />} color="indigo" variant="light">
                {tx("This action is electronically signed. Re-enter your password to sign.")}
              </Alert>
              <PasswordInput label={tx("Password")} required value={password} onChange={(e) => setPassword(e.currentTarget.value)}
                autoComplete="current-password" data-testid="prompt-password" />
            </>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
            <Button type="submit" disabled={!valid} loading={loading} color={color} data-testid="prompt-confirm">{confirmLabel}</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
