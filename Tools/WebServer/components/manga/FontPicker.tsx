import React, { useEffect, useMemo, useState } from 'react';

import { MangaFontCatalogEntry } from '../../types/manga';
import { useI18n } from '../../contexts/I18nContext';

interface FontPickerProps {
  fonts: MangaFontCatalogEntry[];
  fontId?: string;
  fontFamily: string;
  onChange: (patch: { font_id?: string; font_family: string }) => void;
}

const SOURCE_ORDER: Record<string, number> = {
  builtin: 0,
  project: 1,
  system: 2,
};

const sourceLabelKey = (source: string) => {
  if (source === 'builtin') return 'manga_font_source_builtin';
  if (source === 'project') return 'manga_font_source_project';
  if (source === 'system') return 'manga_font_source_system';
  return 'manga_font_source_other';
};

const normalize = (value: string) => value.trim().toLowerCase();

const findSelectedFont = (
  fonts: MangaFontCatalogEntry[],
  fontId: string | undefined,
  fontFamily: string,
) => {
  const id = String(fontId || '').trim();
  if (id) {
    const byId = fonts.find((font) => font.font_id === id);
    if (byId) return byId;
  }
  const family = normalize(fontFamily);
  if (!family) return null;
  return fonts.find((font) => {
    const values = [
      font.css_family,
      font.display_name,
      font.family || '',
      font.postscript_name || '',
    ].map(normalize);
    return values.includes(family) || values.some((value) => value && family.includes(value));
  }) || null;
};

export const FontPicker: React.FC<FontPickerProps> = ({
  fonts,
  fontId,
  fontFamily,
  onChange,
}) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [customValue, setCustomValue] = useState(fontFamily || '');

  useEffect(() => {
    setCustomValue(fontFamily || '');
  }, [fontFamily]);

  const selectedFont = findSelectedFont(fonts, fontId, fontFamily);
  const selectedLabel = selectedFont?.display_name || fontFamily || t('manga_font_custom');
  const selectedCssFamily = selectedFont?.css_family || fontFamily || 'sans-serif';

  const filteredFonts = useMemo(() => {
    const needle = normalize(query);
    return fonts
      .filter((font) => font.available)
      .filter((font) => {
        if (!needle) return true;
        return [
          font.display_name,
          font.family || '',
          font.postscript_name || '',
          font.source,
        ].some((value) => normalize(value).includes(needle));
      })
      .sort((a, b) => {
        const sourceDelta = (SOURCE_ORDER[a.source] ?? 9) - (SOURCE_ORDER[b.source] ?? 9);
        if (sourceDelta !== 0) return sourceDelta;
        return a.display_name.localeCompare(b.display_name);
      });
  }, [fonts, query]);

  const groupedFonts = useMemo(() => {
    const groups: Array<{ source: string; fonts: MangaFontCatalogEntry[] }> = [];
    for (const font of filteredFonts) {
      const last = groups[groups.length - 1];
      if (!last || last.source !== font.source) {
        groups.push({ source: font.source, fonts: [font] });
      } else {
        last.fonts.push(font);
      }
    }
    return groups;
  }, [filteredFonts]);

  const selectFont = (font: MangaFontCatalogEntry) => {
    onChange({ font_id: font.font_id, font_family: font.css_family || font.display_name });
    setOpen(false);
    setQuery('');
    setCustomValue(font.css_family || font.display_name);
  };

  const applyCustomFont = () => {
    const value = customValue.trim();
    if (!value) return;
    onChange({ font_id: '', font_family: value });
    setOpen(false);
  };

  return (
    <div className="relative mt-1">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex min-h-10 w-full items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2 text-left text-sm text-slate-200 outline-none transition-colors hover:border-slate-700 focus:border-primary"
      >
        <span className="min-w-0">
          <span className="block truncate" style={{ fontFamily: selectedCssFamily }}>
            {selectedLabel}
          </span>
          {selectedFont ? (
            <span className="mt-0.5 block truncate text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
              {t(sourceLabelKey(selectedFont.source))}
            </span>
          ) : (
            <span className="mt-0.5 block truncate text-[10px] font-semibold text-amber-200">
              {t('manga_font_custom_warning')}
            </span>
          )}
        </span>
        <span className="shrink-0 text-slate-500">{open ? '^' : 'v'}</span>
      </button>

      {open && (
        <div className="mt-1 w-full overflow-hidden rounded-lg border border-slate-800 bg-slate-950 shadow-xl shadow-slate-950/40">
          <div className="border-b border-slate-800 p-2">
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('manga_font_search_placeholder')}
              className="h-9 w-full rounded-md border border-slate-800 bg-slate-900/80 px-2 text-xs text-slate-200 outline-none focus:border-primary"
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {groupedFonts.length === 0 ? (
              <div className="px-3 py-3 text-xs text-slate-500">{t('manga_font_no_matches')}</div>
            ) : groupedFonts.map((group) => (
              <div key={group.source} className="py-1">
                <div className="px-3 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
                  {t(sourceLabelKey(group.source))}
                </div>
                {group.fonts.map((font) => (
                  <button
                    key={font.font_id}
                    type="button"
                    onClick={() => selectFont(font)}
                    className={`block w-full px-3 py-2 text-left transition-colors hover:bg-slate-900 ${
                      font.font_id === selectedFont?.font_id ? 'bg-primary/10 text-primary' : 'text-slate-200'
                    }`}
                  >
                    <span className="block truncate text-sm" style={{ fontFamily: font.css_family }}>
                      {font.preview_text || '漫画对白 Aa 123'}
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-slate-500">
                      {font.display_name}
                    </span>
                  </button>
                ))}
              </div>
            ))}
          </div>
          <div className="border-t border-slate-800 p-2">
            <details>
              <summary className="cursor-pointer text-[11px] font-semibold text-slate-500 hover:text-slate-300">
                {t('manga_font_custom')}
              </summary>
              <div className="mt-2 flex gap-2">
                <input
                  type="text"
                  value={customValue}
                  onChange={(event) => setCustomValue(event.target.value)}
                  className="min-w-0 flex-1 rounded-md border border-slate-800 bg-slate-900/80 px-2 py-2 text-xs text-slate-200 outline-none focus:border-primary"
                />
                <button
                  type="button"
                  onClick={applyCustomFont}
                  className="rounded-md border border-slate-700 px-2 text-xs font-semibold text-slate-300 hover:border-primary hover:text-slate-100"
                >
                  {t('manga_apply')}
                </button>
              </div>
            </details>
          </div>
        </div>
      )}
    </div>
  );
};
