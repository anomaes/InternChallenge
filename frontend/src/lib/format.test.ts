import { describe, expect, it } from 'vitest'
import { initials, money, qty } from './format'

describe('money', () => {
  it('formats Swiss style with two decimals and the currency first', () => {
    expect(money('1751.40', 'EUR')).toBe('EUR 1’751.40')
    expect(money(999, 'CHF')).toBe('CHF 999.00')
  })
  it('shows a dash for missing values, never 0', () => {
    expect(money(null, 'CHF')).toBe('—')
    expect(money(undefined)).toBe('—')
    expect(money('', 'EUR')).toBe('—')
  })
  it('can drop decimals for summaries', () => {
    expect(money('39552.00', null, { decimals: false })).toBe('39’552')
  })
})

describe('qty and initials', () => {
  it('keeps fractional quantities', () => {
    expect(qty('1.5')).toBe('1.5')
    expect(qty('20000')).toBe('20’000')
  })
  it('builds initials', () => {
    expect(initials('Daniela Huber')).toBe('DH')
    expect(initials(null)).toBe('?')
  })
})
