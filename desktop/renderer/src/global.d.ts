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
      /** TTS 克隆音色的参考音频（wav/mp3/…），返回绝对路径。 */
      pickAudio(defaultDir?: string): Promise<string[]>;
      pickProposal(defaultDir?: string): Promise<string | null>;
      skill: {
        status(): Promise<{
          ok: boolean;
          error?: string;
          name: string;
          targetDir: string;
          installed: boolean;
          upToDate: boolean;
          fileCount: number;
          installedAt: number;
        }>;
        install(paths: { output_dir: string; export_dir: string }): Promise<{
          ok: boolean;
          error?: string;
          targetDir: string;
          installed: boolean;
          upToDate: boolean;
          fileCount: number;
        }>;
      };
      aiKey: {
        set(text: string): Promise<{ ok: boolean; reason?: string }>;
        get(): Promise<string>;
        clear(): Promise<{ ok: boolean }>;
        status(): Promise<{
          ok: boolean;
          /** 本机加密永远可用；保留字段是为了未来兼容 */
          available: boolean;
          has: boolean;
          /** local = 已落盘加密；none = 未配置 */
          backend: 'local' | 'none';
          persistent: boolean;
          /** 有密文但解不开（主密钥丢了/文件被改）→ 需要重填 */
          broken?: boolean;
          /** 更早版本用 safeStorage 存的密文（本方案读不了） */
          legacy?: boolean;
        }>;
      };
      pickDirectory(payload: { title?: string; defaultPath?: string }): Promise<string | null>;
      writeClipboard(text: string): Promise<boolean>;
      clearMainLog(): Promise<{ removed: number; freed: number }>;
      revealInFinder(target: string): Promise<void>;
      openPath(target: string): Promise<string>;
      setTitle(title: string): void;
      setDocumentEdited(dirty: boolean): void;
      setTheme(theme: 'light' | 'dark' | 'mincho'): void;
      getSetupState(): Promise<SetupState>;
      completeSetup(modelsDir: string): Promise<{ ok: boolean; modelsDir: string }>;
      pickModelsDir(): Promise<string | null>;
      setModelsDir(modelsDir: string): Promise<{ ok: boolean; modelsDir: string }>;
      onMenu(cb: (ev: MenuEvent) => void): () => void;
      onQuitPrompt(cb: (payload: { files: CleanupFile[] }) => void): () => void;
      onQuitCancelled(cb: () => void): () => void;
      /** 主进程已在退出：之后的 sidecar:down 是收尾，不是内核崩溃（preload.cjs 的 app:quitting） */
      onQuitting(cb: () => void): () => void;
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

/** Vite 静态资源：图标等图片 */
declare module '*.png' {
  const src: string;
  export default src;
}
