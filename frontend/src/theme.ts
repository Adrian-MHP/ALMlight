import { createTheme, type MantineColorsTuple } from "@mantine/core";

// Industrial engineering look: petrol-teal accent on deep navy chrome, compact radii and dense tables — the visual
// language engineers know from enterprise PLM/ALM suites, without copying any vendor's branding.
const petrol: MantineColorsTuple = ["#e6f6f7", "#ccecee", "#9bd8dc", "#66c2c8", "#3aafb7", "#1f9ea8", "#0f8a94",
  "#0b7a84", "#076770", "#03515a"];
const navy: MantineColorsTuple = ["#eef2f6", "#d9e1ea", "#b0c0d2", "#849cb8", "#5e7da2", "#466a94", "#385c88",
  "#2a4a72", "#1d3a5c", "#0d1b2a"];

export const theme = createTheme({
  primaryColor: "petrol",
  primaryShade: { light: 7, dark: 4 },
  colors: { petrol, navy },
  defaultRadius: "sm",
  fontFamily: "'Inter Variable', Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMonospace: "ui-monospace, SFMono-Regular, 'JetBrains Mono', Menlo, Consolas, monospace",
  headings: {
    fontWeight: "600",
    sizes: { h1: { fontSize: "1.6rem" }, h2: { fontSize: "1.35rem" }, h3: { fontSize: "1.15rem" }, h4: { fontSize: "1.02rem" } },
  },
  components: {
    Badge: { defaultProps: { radius: "xs" } },
    Button: { defaultProps: { radius: "sm" } },
    Card: { defaultProps: { radius: "sm" } },
    Paper: { defaultProps: { radius: "sm" } },
    Table: { defaultProps: { verticalSpacing: 6, highlightOnHover: true } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 250 } },
    Tabs: { defaultProps: { color: "petrol" } },
    NavLink: { defaultProps: { color: "petrol" } },
  },
});
