import { IconBrandAzure, IconBrandBitbucket, IconBrandGithub, IconBrandGitlab, IconGitBranch } from "@tabler/icons-react";

/** Logo of the Git hosting service a repository lives on. */
export function ProviderIcon({ provider, size = 16 }: { provider: string; size?: number }) {
  if (provider === "github") return <IconBrandGithub size={size} />;
  if (provider === "gitlab") return <IconBrandGitlab size={size} />;
  if (provider === "bitbucket") return <IconBrandBitbucket size={size} />;
  if (provider === "azure") return <IconBrandAzure size={size} />;
  return <IconGitBranch size={size} />;
}
