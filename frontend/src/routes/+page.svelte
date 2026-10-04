<script lang="ts">
	import { onMount } from 'svelte';
	import { Chessground } from '@lichess-org/chessground';
	import { endgameGlyphs, glyphToSvg } from '@lichess-org/chessground/glyph';
	import { Button } from '$lib/components/ui/button/index.js';
	import '@lichess-org/chessground/assets/chessground.base.css';
	import '@lichess-org/chessground/assets/chessground.brown.css';
	import '@lichess-org/chessground/assets/chessground.cburnett.css';

	type Square = Parameters<ReturnType<typeof Chessground>['move']>[0];
	type PlayerColor = 'white' | 'black';

	type SessionSummary = {
		date: string;
		completed: number;
		total: number;
	};

	type SessionPuzzle = {
		position: number;
		puzzle_id: string;
		fen: string;
		moves: string;
		last_move: string;
		legal_moves: string[][];
		checkmate_kings: (string | null)[];
		rating: number;
		themes: string;
		result: 'success' | 'failed' | null;
		elapsed_ms: number | null;
	};

	type SavedResult = {
		result: 'success' | 'failed';
		elapsed_ms: number;
	};

	type SessionPayload = {
		date: string;
		puzzles: SessionPuzzle[];
		completed: number;
	};

	const startingFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
	const backendResponseError = 'Backend unavailable or returned an invalid response.';
	const correctMoveGlyph = glyphToSvg(1)['✓'](0);
	const incorrectMoveGlyph = glyphToSvg(1)['✗'](0);
	const mateGlyph = endgameGlyphs(1).mate(0);

	let boardElement = $state<HTMLDivElement>();
	let ground: ReturnType<typeof Chessground> | undefined;
	let sessions = $state<SessionSummary[]>([]);
	let currentSession = $state<SessionPayload | null>(null);
	let currentIndex = $state(0);
	let historyLoading = $state(true);
	let sessionLoading = $state(false);
	let error = $state('');
	let syncState = $state<'idle' | 'loading' | 'success' | 'error'>('idle');
	let syncMessage = $state('');
	let currentPuzzle = $derived(currentSession?.puzzles[currentIndex]);
	let recordedCount = $derived(currentSession?.puzzles.filter((puzzle) => puzzle.result !== null).length ?? 0);
	let sessionComplete = $state(false);
	let solutionIndex = $state(0);
	let attemptStartedAt = $state<number | undefined>(undefined);
	let displayElapsedMs = $state(0);
	let timerId: number | undefined;
	let attemptFailed = $state(false);
	let failurePersisted = $state(false);
	let feedback = $state('');
	let savingResult = $state(false);
	let resultSaveError = $state('');
	let puzzleSolved = $state(false);

	async function requestError(response: Response, fallback: string) {
		try {
			const payload = (await response.json()) as { detail?: unknown };
			return typeof payload.detail === 'string' ? payload.detail : fallback;
		} catch {
			return backendResponseError;
		}
	}

	async function responseJson<T>(response: Response) {
		try {
			return (await response.json()) as T;
		} catch (caught) {
			if (caught instanceof SyntaxError) {
				throw new Error(backendResponseError);
			}
			throw caught;
		}
	}

	function caughtMessage(caught: unknown, fallback: string) {
		if (caught instanceof SyntaxError || caught instanceof TypeError) {
			return backendResponseError;
		}
		return caught instanceof Error ? caught.message : fallback;
	}

	function formatElapsed(elapsedMs: number) {
		const totalSeconds = Math.floor(elapsedMs / 1000);
		return `${String(Math.floor(totalSeconds / 60)).padStart(2, '0')}:${String(totalSeconds % 60).padStart(2, '0')}.${Math.floor((elapsedMs % 1000) / 100)}`;
	}

	function stopTimer() {
		if (timerId !== undefined) {
			clearInterval(timerId);
			timerId = undefined;
		}
		attemptStartedAt = undefined;
	}

	function elapsedSinceStart() {
		return attemptStartedAt === undefined
			? displayElapsedMs
			: Math.max(0, Math.round(performance.now() - attemptStartedAt));
	}

	function startTimer() {
		stopTimer();
		attemptStartedAt = performance.now();
		displayElapsedMs = 0;
		timerId = window.setInterval(() => {
			displayElapsedMs = elapsedSinceStart();
		}, 100);
	}

	function puzzleColor(fen: string): PlayerColor {
		return fen.split(/\s+/)[1] === 'b' ? 'black' : 'white';
	}

	function parseUci(token: string) {
		if (!/^[a-h][1-8][a-h][1-8]$/.test(token)) return null;
		return {
			from: token.slice(0, 2) as Square,
			to: token.slice(2, 4) as Square
		};
	}

	function puzzleMoves(puzzle: SessionPuzzle) {
		return puzzle.moves.trim() ? puzzle.moves.trim().split(/\s+/) : [];
	}

	function legalDestinations(puzzle: SessionPuzzle, index: number) {
		const dests = new Map<Square, Square[]>();
		for (const token of puzzle.legal_moves[index] ?? []) {
			const parsed = parseUci(token.slice(0, 4));
			if (!parsed) continue;
			const destinations = dests.get(parsed.from) ?? [];
			destinations.push(parsed.to);
			dests.set(parsed.from, destinations);
		}
		return dests;
	}

	function setLocalResult(
		date: string,
		position: number,
		result: 'success' | 'failed',
		elapsedMs: number
	) {
		if (!currentSession || currentSession.date !== date) return;
		currentSession = {
			...currentSession,
			puzzles: currentSession.puzzles.map((puzzle) =>
				puzzle.position === position ? { ...puzzle, result, elapsed_ms: elapsedMs } : puzzle
			)
		};
	}

	async function saveResult(
		date: string,
		position: number,
		success: boolean,
		elapsedMs: number
	): Promise<SavedResult | null> {
		if (savingResult) return null;
		savingResult = true;
		resultSaveError = '';
		try {
			const response = await fetch(`/api/sessions/${encodeURIComponent(date)}/${position}/result`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ success, elapsed_ms: elapsedMs })
			});
			if (!response.ok) {
				throw new Error(await requestError(response, 'Could not save the puzzle result.'));
			}
			const saved = await responseJson<SavedResult>(response);
			if (
				!saved ||
				(saved.result !== 'success' && saved.result !== 'failed') ||
				typeof saved.elapsed_ms !== 'number'
			) {
				throw new Error(backendResponseError);
			}
			setLocalResult(date, position, saved.result, saved.elapsed_ms);
			return saved;
		} catch (caught) {
			if (currentSession?.date === date && currentSession.puzzles[currentIndex]?.position === position) {
				resultSaveError = caughtMessage(caught, 'Could not save the puzzle result.');
				if (success) feedback = 'Solved, but the result could not be saved.';
			}
			return null;
		} finally {
			savingResult = false;
		}
	}

	function configureBoard(puzzle: SessionPuzzle, interactive: boolean) {
		if (!ground) return;
		const color = puzzleColor(puzzle.fen);
		const lastMove = parseUci(puzzle.last_move);
		ground.stop();
		ground.setAutoShapes([]);
		ground.set({
			fen: puzzle.fen,
			orientation: color,
			turnColor: color,
			lastMove: lastMove ? [lastMove.from, lastMove.to] : undefined,
			...(interactive
				? {
				movable: {
					free: false,
					color,
					dests: legalDestinations(puzzle, Math.floor(solutionIndex / 2)),
					showDests: true,
					events: { after: handleUserMove }
				},
					premovable: { enabled: false }
				}
				: {})
		});
	}

	function completePuzzle() {
		const session = currentSession;
		const puzzle = currentPuzzle;
		if (!session || !puzzle || puzzleSolved) return;

		const elapsedMs = attemptFailed ? displayElapsedMs : elapsedSinceStart();
		stopTimer();
		displayElapsedMs = elapsedMs;
		puzzleSolved = true;
		ground?.stop();

		if (attemptFailed) {
			feedback = failurePersisted
				? 'Solved on retry — first attempt recorded as failed.'
				: puzzle.result === 'success'
					? 'Result was already recorded as successful.'
				: 'Solved on retry — first attempt failed, but the result could not be saved.';
			return;
		}

		feedback = 'Solved';
		void saveResult(session.date, puzzle.position, true, elapsedMs).then((saved) => {
			if (saved?.result === 'failed') {
				feedback = 'Solved, but this puzzle was already recorded as failed.';
			}
		});
	}

	function resetForRetry(puzzle: SessionPuzzle) {
		solutionIndex = 0;
		puzzleSolved = false;
		feedback = 'Wrong — try again';
		configureBoard(puzzle, true);
	}

	function handleUserMove(orig: Square, dest: Square) {
		const puzzle = currentPuzzle;
		if (!puzzle || puzzleSolved || (puzzle.result !== null && !attemptFailed)) return;

		const moves = puzzleMoves(puzzle);
		const expected = moves[solutionIndex];
		if (!expected || `${orig}${dest}` !== expected.slice(0, 4)) {
			if (!attemptFailed) {
				attemptFailed = true;
				failurePersisted = false;
				const elapsedMs = elapsedSinceStart();
				stopTimer();
				displayElapsedMs = elapsedMs;
				const date = currentSession?.date;
				if (date) {
					void saveResult(date, puzzle.position, false, elapsedMs).then((saved) => {
						if (saved?.result === 'failed') {
							failurePersisted = true;
							if (
								puzzleSolved &&
								currentSession?.date === date &&
								currentPuzzle?.position === puzzle.position
							) {
								feedback = 'Solved on retry — first attempt recorded as failed.';
							}
						} else if (
							saved?.result === 'success' &&
							currentSession?.date === date &&
							currentPuzzle?.position === puzzle.position
						) {
							feedback = 'Result was already recorded as successful.';
						}
					});
				}
			}
			feedback = 'Wrong — try again';
			const retryDate = currentSession?.date;
			const retryPosition = puzzle.position;
			ground?.setAutoShapes([
				{ orig: dest, customSvg: { html: incorrectMoveGlyph, center: 'orig' } }
			]);
			window.setTimeout(() => {
				if (currentSession?.date === retryDate && currentPuzzle?.position === retryPosition) {
					resetForRetry(puzzle);
				}
			}, 300);
			return;
		}

		const userTurnIndex = Math.floor(solutionIndex / 2);
		solutionIndex += 1;
		const opponentMove = moves[solutionIndex];
		if (opponentMove) {
			const parsed = parseUci(opponentMove);
			if (!parsed) {
				stopTimer();
				puzzleSolved = true;
				feedback = 'Puzzle data is invalid.';
				ground?.stop();
				return;
			}
			const responseDate = currentSession?.date;
			const responsePosition = puzzle.position;
			const expectedSolutionIndex = solutionIndex;
			window.setTimeout(() => {
				if (
					currentSession?.date !== responseDate ||
					currentPuzzle?.position !== responsePosition ||
					solutionIndex !== expectedSolutionIndex
				) {
					return;
				}
				ground?.move(parsed.from, parsed.to);
				ground?.setAutoShapes([]);
				solutionIndex += 1;
				ground?.set({
					turnColor: puzzleColor(puzzle.fen),
					movable: {
						dests: legalDestinations(puzzle, Math.floor(solutionIndex / 2)),
						showDests: true
					}
				});
				if (solutionIndex >= moves.length) completePuzzle();
				else feedback = 'Your move';
			}, 300);
			return;
		}

		const successShapes = [
			{ orig: dest, customSvg: { html: correctMoveGlyph, center: 'orig' as const } }
		];
		const kingSquare = puzzle.checkmate_kings[userTurnIndex];
		if (kingSquare && /^[a-h][1-8]$/.test(kingSquare)) {
			successShapes.push({ orig: kingSquare as Square, customSvg: { html: mateGlyph, center: 'orig' as const } });
		}
		ground?.setAutoShapes(successShapes);

		if (solutionIndex >= moves.length) completePuzzle();
		else feedback = 'Your move';
	}

	function activatePuzzle(puzzle: SessionPuzzle | undefined) {
		stopTimer();
		solutionIndex = 0;
		attemptFailed = puzzle?.result === 'failed';
		failurePersisted = puzzle?.result === 'failed';
		puzzleSolved = puzzle?.result !== null && puzzle?.result !== undefined;
		displayElapsedMs = puzzle?.elapsed_ms ?? 0;
		feedback = '';
		resultSaveError = '';

		if (!puzzle) {
			ground?.stop();
			return;
		}
		if (puzzle.result !== null) {
			configureBoard(puzzle, false);
			feedback =
				puzzle.result === 'success' ? 'Solved — result already recorded' : 'Failed — result already recorded';
			return;
		}

		puzzleSolved = false;
		configureBoard(puzzle, true);
		feedback = 'Your move';
		startTimer();
	}

	function enterSessionComplete(displayPuzzle?: SessionPuzzle) {
		sessionComplete = true;
		stopTimer();
		solutionIndex = 0;
		attemptFailed = false;
		failurePersisted = false;
		puzzleSolved = true;
		displayElapsedMs = 0;
		feedback = '';
		resultSaveError = '';
		if (displayPuzzle) configureBoard(displayPuzzle, false);
		else ground?.stop();
	}

	function activateSession(session: SessionPayload) {
		currentSession = session;
		const firstUnfinished = session.puzzles.findIndex((puzzle) => puzzle.result === null);
		const index = firstUnfinished === -1 ? Math.max(session.puzzles.length - 1, 0) : firstUnfinished;
		currentIndex = index;
		if (firstUnfinished === -1) {
			enterSessionComplete(session.puzzles[index]);
			return;
		}
		sessionComplete = false;
		activatePuzzle(session.puzzles[index]);
	}

	async function nextPuzzle() {
		const session = currentSession;
		const puzzle = currentPuzzle;
		if (savingResult || !session || !puzzle || !puzzleSolved || puzzle.result === null) return;

		const nextIndex = session.puzzles.findIndex(
			(candidate, index) => index > currentIndex && candidate.result === null
		);
		if (nextIndex === -1) {
			enterSessionComplete();
		} else {
			sessionComplete = false;
			currentIndex = nextIndex;
			activatePuzzle(session.puzzles[nextIndex]);
		}
		await loadSessions();
	}

	async function loadSessions() {
		historyLoading = true;
		error = '';
		try {
			const response = await fetch('/api/sessions');
			if (!response.ok) {
				throw new Error(await requestError(response, 'Could not load session history.'));
			}
			sessions = await responseJson<SessionSummary[]>(response);
		} catch (caught) {
			error = caughtMessage(caught, 'Could not load session history.');
		} finally {
			historyLoading = false;
		}
	}

	async function sync() {
		syncState = 'loading';
		syncMessage = 'Syncing Chess.com games…';
		error = '';
		try {
			const response = await fetch('/api/sync', { method: 'POST' });
			if (!response.ok) {
				throw new Error(await requestError(response, 'Synchronization failed.'));
			}
			const result = await responseJson<{
				eligible: number;
				imported: number;
				mistakes: number;
			}>(response);
			syncState = 'success';
			syncMessage = `Sync complete: ${result.eligible} eligible, ${result.imported} imported, ${result.mistakes} mistakes.`;
		} catch (caught) {
			syncState = 'error';
			syncMessage = caughtMessage(caught, 'Synchronization failed.');
		}
	}

	async function startToday() {
		sessionLoading = true;
		error = '';
		try {
			const response = await fetch('/api/sessions/today', { method: 'POST' });
			if (!response.ok) {
				throw new Error(await requestError(response, 'Could not start today’s session.'));
			}
			const session = await responseJson<SessionPayload>(response);
			activateSession(session);
			await loadSessions();
		} catch (caught) {
			error = caughtMessage(caught, 'Could not start today’s session.');
		} finally {
			sessionLoading = false;
		}
	}

	async function openSession(date: string) {
		sessionLoading = true;
		error = '';
		try {
			const response = await fetch(`/api/sessions/${encodeURIComponent(date)}`);
			if (!response.ok) {
				throw new Error(await requestError(response, 'Could not load that session.'));
			}
			const session = await responseJson<SessionPayload>(response);
			activateSession(session);
		} catch (caught) {
			error = caughtMessage(caught, 'Could not load that session.');
		} finally {
			sessionLoading = false;
		}
	}

	onMount(() => {
		if (boardElement) {
			ground = Chessground(boardElement, {
				fen: startingFen,
				viewOnly: false
			});
			ground.stop();
		}

		void loadSessions();

		return () => {
			stopTimer();
			ground?.destroy();
		};
	});
</script>

<svelte:head>
	<title>Chess Trainer</title>
</svelte:head>

<main class="min-h-screen bg-background text-foreground">
	<div class="mx-auto flex min-h-screen max-w-[1800px] flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:gap-6 lg:px-8 lg:py-4">
		<aside class="flex w-full flex-col gap-4 border-b border-border pb-4 lg:w-72 lg:shrink-0 lg:border-b-0 lg:border-r lg:pr-6 lg:pb-0">
			<header class="space-y-1">
				<p class="text-xs font-semibold uppercase tracking-[0.24em] text-primary">Chess Trainer</p>
				<h1 class="text-2xl font-semibold tracking-tight">Tactical training</h1>
				<p class="text-sm text-muted-foreground">Patterns from your recent games.</p>
			</header>

			<section class="grid gap-2 sm:flex lg:grid">
				<Button
					variant="default"
					size="lg"
					onclick={sync}
					disabled={syncState === 'loading'}
				>
					{syncState === 'loading' ? 'Syncing…' : 'Sync games'}
				</Button>
				<Button
					variant="secondary"
					size="lg"
					onclick={startToday}
					disabled={sessionLoading || savingResult}
				>
					{sessionLoading ? 'Loading…' : 'Start / Resume Today'}
				</Button>
			</section>

			<div class="space-y-1 text-sm" aria-live="polite">
				{#if syncMessage}
					<p class={syncState === 'error' ? 'text-destructive' : 'text-primary'}>{syncMessage}</p>
				{/if}
				{#if error}
					<p class="text-destructive">{error}</p>
				{/if}
			</div>

			<section class="min-h-0 space-y-3 lg:flex-1 lg:overflow-y-auto">
				<div>
					<h2 class="text-lg font-semibold">Session history</h2>
					<p class="mt-1 text-sm text-muted-foreground">Reopen a daily session.</p>
				</div>

				{#if historyLoading}
					<p class="text-sm text-muted-foreground" role="status">Loading sessions…</p>
				{:else if sessions.length === 0}
					<p class="text-sm text-muted-foreground">No sessions yet. Start today’s training to create one.</p>
				{:else}
					<div class="space-y-2">
						{#each sessions as session}
							<button
								type="button"
								class="flex w-full items-center justify-between border px-3 py-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50 {currentSession?.date === session.date ? 'border-primary bg-accent text-accent-foreground' : 'border-border bg-background hover:bg-accent'}"
								onclick={() => openSession(session.date)}
								disabled={sessionLoading || savingResult}
								aria-pressed={currentSession?.date === session.date}
							>
								<span class="font-medium">{session.date}</span>
								<span class="text-sm text-muted-foreground">{session.completed}/{session.total}</span>
							</button>
						{/each}
					</div>
				{/if}
			</section>
		</aside>

		<section class="flex min-w-0 flex-1 flex-col gap-3" aria-busy={sessionLoading}>
			{#if currentSession && currentPuzzle}
				<div class="flex shrink-0 flex-col gap-2 border-b border-border pb-3 sm:flex-row sm:items-end sm:justify-between">
					<div>
						<p class="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Session {currentSession.date}</p>
						<h2 class="mt-1 text-2xl font-semibold tracking-tight">
							{sessionComplete ? 'Session complete' : `Puzzle ${currentPuzzle.position} of ${currentSession.puzzles.length}`}
						</h2>
						{#if sessionComplete}
							<p class="mt-1 text-sm text-muted-foreground">{recordedCount} / {currentSession.puzzles.length} puzzles recorded</p>
						{/if}
					</div>
					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
						{#if !sessionComplete}
							<span role="timer" aria-label="Elapsed time">Time: {formatElapsed(displayElapsedMs)}</span>
							{#if feedback}
								<span aria-live="polite">{feedback}</span>
							{/if}
							{#if savingResult}
								<span role="status" aria-live="polite">Saving result…</span>
							{/if}
							{#if resultSaveError}
								<span class="text-destructive" role="alert">{resultSaveError}</span>
							{/if}
							<span>{recordedCount}/{currentSession.puzzles.length} recorded</span>
							<span>Rating: {currentPuzzle.rating}</span>
							<span>Themes: {currentPuzzle.themes}</span>
							{#if puzzleSolved}
								<Button
									variant="secondary"
									size="lg"
									onclick={nextPuzzle}
									disabled={savingResult || currentPuzzle.result === null}
								>
									Next puzzle
								</Button>
							{/if}
						{/if}
					</div>
				</div>
			{:else}
				<div class="shrink-0 border-b border-border pb-3">
					<h2 class="text-2xl font-semibold tracking-tight">Ready to train?</h2>
					<p class="mt-1 text-sm text-muted-foreground">Start today’s session or choose one from your history.</p>
				</div>
			{/if}

			<div class="flex min-h-0 flex-1 items-center justify-center bg-muted p-2 sm:p-4">
				<div class="board aspect-square w-[min(86vh,100%)] max-w-full" bind:this={boardElement}></div>
			</div>
		</section>
	</div>
</main>

<style>
	:global(.cg-wrap coords) {
		font-size: clamp(0.75rem, 1.4vw, 1rem);
	}
</style>
