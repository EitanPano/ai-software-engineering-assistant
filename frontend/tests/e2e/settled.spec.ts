import { expect, test } from '@playwright/test'

import { settled } from './support'

// `settled` backs every axe scan, so it must survive what a live page does: a transition that is
// retargeted or removed mid-fade cancels its animation, and the replacement must still be awaited.
const PAGE = `
  <style>
    #host button { opacity: 1; transition: opacity 400ms linear; }
    #host button:disabled { opacity: 0.5; }
  </style>
  <div id="host"><button disabled>Send</button></div>
`

test.describe('settled', () => {
  test('waits for a replacement transition when the first is cancelled mid-fade', async ({
    page,
  }) => {
    await page.setContent(PAGE)
    const host = page.locator('#host')
    await host.evaluate((element) => {
      const button = element.querySelector('button')
      if (!button) throw new Error('no button')
      button.disabled = false // fades up
      button.getBoundingClientRect() // flush style so the transition starts
      setTimeout(() => {
        button.disabled = true // retarget: cancels the fade up, starts a fade down
        setTimeout(() => {
          button.disabled = false // and back up
        }, 100)
      }, 100)
    })

    await settled(host)

    // Nothing finite is left running, and the button rests at its end state.
    const running = await host.evaluate(
      (element) =>
        element.getAnimations({ subtree: true }).filter((a) => a.playState === 'running').length,
    )
    expect(running).toBe(0)
    const opacity = await page
      .getByRole('button', { name: 'Send' })
      .evaluate((element) => getComputedStyle(element).opacity)
    expect(opacity).toBe('1')
  })

  test('resolves when the animated element is removed mid-fade', async ({ page }) => {
    await page.setContent(PAGE)
    const host = page.locator('#host')
    await host.evaluate((element) => {
      const button = element.querySelector('button')
      if (!button) throw new Error('no button')
      button.disabled = false
      button.getBoundingClientRect()
      setTimeout(() => {
        button.remove()
      }, 100)
    })

    await expect(settled(host)).resolves.toBeUndefined()
  })
})
