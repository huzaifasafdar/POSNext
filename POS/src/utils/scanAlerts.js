let audioContext = null
let lastUnknownItemAlertAt = 0
let unknownItemAudioBuffer = null
let unknownItemAudioLoadPromise = null
let unknownItemAudioLoadFailed = false

// Change only this line to test other ERPNext/Frappe system sounds.
const UNKNOWN_ITEM_ALERT_URL = "/assets/pos_next/pos/sounds/scan-alert.mp3?v=2"

function getAudioContext() {
	if (typeof window === "undefined") {
		return null
	}

	const AudioContextClass = window.AudioContext || window.webkitAudioContext
	if (!AudioContextClass) {
		return null
	}

	if (!audioContext) {
		audioContext = new AudioContextClass()
	}

	return audioContext
}

async function getUnknownItemAudioBuffer(context) {
	if (unknownItemAudioBuffer) {
		return unknownItemAudioBuffer
	}

	if (unknownItemAudioLoadFailed) {
		return null
	}

	if (!unknownItemAudioLoadPromise) {
		unknownItemAudioLoadPromise = fetch(UNKNOWN_ITEM_ALERT_URL)
			.then((response) => {
				if (!response.ok) {
					throw new Error(`Alert sound not found: ${response.status}`)
				}
				return response.arrayBuffer()
			})
			.then((audioData) => context.decodeAudioData(audioData))
			.then((buffer) => {
				unknownItemAudioBuffer = buffer
				return buffer
			})
			.catch((error) => {
				unknownItemAudioLoadPromise = null
				unknownItemAudioLoadFailed = true
				console.warn("Unable to load unknown item alert sound", error)
				return null
			})
	}

	return unknownItemAudioLoadPromise
}

function playAudioFileAlert(context, startTime, buffer) {
	const source = context.createBufferSource()
	const gain = context.createGain()

	source.buffer = buffer
	gain.gain.setValueAtTime(5, startTime)

	source.connect(gain)
	gain.connect(context.destination)
	source.start(startTime)
}

function playFallbackAlert(context, startTime) {
	const buzzer = context.createOscillator()
	const gain = context.createGain()

	buzzer.type = "square"
	buzzer.frequency.setValueAtTime(1200, startTime)

	gain.gain.setValueAtTime(0.0001, startTime)
	gain.gain.exponentialRampToValueAtTime(3.5, startTime + 0.01)
	gain.gain.exponentialRampToValueAtTime(0.0001, startTime + 0.5)

	buzzer.connect(gain)
	gain.connect(context.destination)
	buzzer.start(startTime)
	buzzer.stop(startTime + 0.52)
}

export async function playUnknownItemAlert() {
	const now = Date.now()
	if (now - lastUnknownItemAlertAt < 250) {
		return
	}
	lastUnknownItemAlertAt = now

	try {
		const context = getAudioContext()
		if (!context) {
			return
		}

		if (context.state === "suspended") {
			await context.resume()
		}

		const start = context.currentTime + 0.01
		const buffer = await getUnknownItemAudioBuffer(context)

		if (buffer) {
			playAudioFileAlert(context, start, buffer)
		} else {
			playFallbackAlert(context, start)
		}
	} catch (error) {
		console.warn("Unable to play unknown item alert", error)
	}
}
