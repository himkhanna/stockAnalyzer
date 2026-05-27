import type { ReactNode } from "react";

interface Props {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
}

export function EmptyState({ title, children, icon }: Props) {
  return (
    <div className="card p-12 text-center animate-fade-in">
      {icon && <div className="text-zinc-400 mb-3 flex justify-center">{icon}</div>}
      <div className="font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
        {title}
      </div>
      {children && (
        <div className="text-sm text-zinc-500">{children}</div>
      )}
    </div>
  );
}
