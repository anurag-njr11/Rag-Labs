export const tabPanelProps = (idPrefix: string, value: string) => ({
  role: 'tabpanel' as const,
  id: `${idPrefix}-panel-${value}`,
  'aria-labelledby': `${idPrefix}-tab-${value}`,
  tabIndex: 0,
})
