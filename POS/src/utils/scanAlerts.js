let audioContext = null
let lastUnknownItemAlertAt = 0

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

function playDangerAlert(context, startTime, duration = 1.35) {
	const buzzer = context.createOscillator()
	const masterGain = context.createGain()

	buzzer.type = "sawtooth"
	buzzer.frequency.setValueAtTime(1800, startTime)

	masterGain.gain.setValueAtTime(0.0001, startTime)
	masterGain.gain.exponentialRampToValueAtTime(8, startTime + 0.01)
	masterGain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration)

	buzzer.connect(masterGain)
	masterGain.connect(context.destination)

	buzzer.start(startTime)
	buzzer.stop(startTime + duration + 0.02)
}

export function playUnknownItemAlert() {
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
			context.resume()
		}

		const start = context.currentTime + 0.01
		playDangerAlert(context, start)
	} catch (error) {
		console.warn("Unable to play unknown item alert", error)
	}
}
