import { createContext, useContext, useMemo } from 'react'
import zh from './locales/zh.json'
import en from './locales/en.json'

export type Language = 'zh' | 'en'

export const DEFAULT_LANGUAGE: Language = 'zh'

export const resources = {
  zh: { translation: zh },
  en: { translation: en },
} as const

type Resources = typeof resources
export type Namespace = keyof Resources[Language]
type TranslationValue = string | Record<string, unknown>

export function getNestedValue(
  obj: TranslationValue | undefined,
  path: string
): string | undefined {
  const keys = path.split('.')
  let current: unknown = obj
  for (const key of keys) {
    if (current && typeof current === 'object' && key in current) {
      current = (current as Record<string, unknown>)[key]
    } else {
      return undefined
    }
  }
  return typeof current === 'string' ? current : undefined
}

export function interpolate(template: string, options?: Record<string, unknown>): string {
  if (!options) return template
  return template.replace(/\{\{(\s*\w+\s*)\}\}/g, (_, name) => {
    const key = name.trim()
    const value = options[key]
    return value === undefined || value === null ? '' : String(value)
  })
}

export interface I18nContextValue {
  language: Language
  changeLanguage: (lang: Language) => void
  t: (key: string, options?: Record<string, unknown>) => string
}

export const I18nContext = createContext<I18nContextValue | null>(null)

export const useTranslation = () => {
  const context = useContext(I18nContext)
  if (!context) {
    throw new Error('useTranslation must be used within an I18nProvider')
  }
  const { language, changeLanguage, t } = context
  return useMemo(
    () => ({
      t,
      i18n: { language, changeLanguage },
    }),
    [language, changeLanguage, t]
  )
}
