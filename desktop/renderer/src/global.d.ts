/** preload 通过 contextBridge 暴露的桥。渲染进程只能看到这些。 */
export interface SidecarHandshake {
  port: number;
  token: string;
  pid: number;
  version?: string;
}

export interface SetupState {
  firstRun: boolean;
  modelsDir: string;
  defaultModelsDir: string;
  dataDir: string;
  preferencesPath: string;
  ffmpeg: string;
  appVersion: string;
}

export interface CleanupFile {
  path: string;
  name: string;
  kind: 'fragment' | 'proxy';
  size: number;
  mtime: number;
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
      pickSubtitle(defaultDir?: string): Promise<string | null>;
      pickDirectory(payload: { title?: string; defaultPath?: string }): Promise<string | null>;
      writeClipboard(text: string): Promise<boolean>;
      revealInFinder(target: string): Promise<void>;
      openPath(target: string): Promise<string>;
      setTitle(title: string): void;
      setDocumentEdited(dirty: boolean): void;
      setTheme(theme: 'light' | 'dark'): void;
      getSetupState(): Promise<SetupState>;
      completeSetup(modelsDir: string): Promise<{ ok: boolean; modelsDir: string }>;
      pickModelsDir(): Promise<string | null>;
      setModelsDir(modelsDir: string): Promise<{ ok: boolean; modelsDir: string }>;
      onMenu(cb: (ev: MenuEvent) => void): () => void;
      onQuitPrompt(cb: (payload: { files: CleanupFile[] }) => void): () => void;
      onQuitCancelled(cb: () => void): () => void;
      getQuitPrompt(): Promise<{ files: CleanupFile[] } | null>;
      confirmQuit(keepPaths: string[]): Promise<{ ok: boolean; removed: number; failed: number }>;
      cancelQuit(): Promise<void>;
      onFileOpened(cb: (path: string) => void): () => void;
      getPathForFile(file: File): string;
      getDevSeed?(): Promise<{ mediaPath: string; cues?: any[] } | null>;
    };
  }
}

export {};
