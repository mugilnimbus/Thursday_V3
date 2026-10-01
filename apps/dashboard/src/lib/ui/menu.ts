export interface MenuItem {
  label: string;
  icon: string;
  run: () => void;
  danger?: boolean;
  separated?: boolean;
}
