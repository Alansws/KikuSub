/** preload 通过 contextBridge 暴露的桥。渲染进程只能看到这些。 */
export interface SidecarHandshake {
  port: number;
  token: string;
  pid: number;
  version?: string;
}

export interface MenuEvent {
  type:
    | 'undo'
    | 'redo'
    | 'settings'
    | 'export'
    | 'inspector'
    | 'theme'
    | 'play'
    | 'prev-cue'
    | 'next-cue'
    | 'view';
  view?: string;
}

declare global {
  interface Window {
    kikusub: {
      info(): Promise<{
        version: string;
        platform: string;
        arch: string;
        dev: boolean;
        repoRoot: string;
      }>;
      getSidecar(): Promise<SidecarHandshake | null>;
      onSidecarReady(cb: (payload: SidecarHandshake) => void): () => void;
      onSidecarDown(cb: (info: { code: number | null; signal: string | null }) => void): () => void;
      pickMedia(): Promise<string | null>;
      revealInFinder(target: string): Promise<void>;
      openPath(target: string): Promise<string>;
      setTitle(title: string): void;
      setDocumentEdited(dirty: boolean): void;
      onMenu(cb: (ev: MenuEvent) => void): () => void;
      onFileOpened(cb: (path: string) => void): () => void;
      getPathForFile(file: File): string;
      getDevSeed?(): Promise<{ mediaPath: string; cues?: any[] } | null>;
    };
  }
}

export {};
