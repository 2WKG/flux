export const load = () => fetch("/api/scenarios");
export const label = `it's a template ${load.name}`;
