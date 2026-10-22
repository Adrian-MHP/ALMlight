import { createTheme } from "@mantine/core";

export const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "md",
  fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMonospace: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  headings: { fontWeight: "650" },
  components: {
    Badge: { defaultProps: { radius: "sm" } },
    Table: { defaultProps: { verticalSpacing: 6, highlightOnHover: true } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 250 } },
  },
});
