<script lang="ts">
	import { onMount } from 'svelte';
	import { Chessground } from '@lichess-org/chessground';
	import { Button } from '$lib/components/ui/button/index.js';
	import '@lichess-org/chessground/assets/chessground.base.css';
	import '@lichess-org/chessground/assets/chessground.brown.css';
	import '@lichess-org/chessground/assets/chessground.cburnett.css';

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
		rating: number;
		themes: string;
		result: 'success' | 'failed' | null;
		elapsed_ms: number | null;
	};

	type SessionPayload = {
		date: string;
		puzzles: SessionPuzzle[];
		completed: number;
	};

	const startingFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
	const backendResponseError = 'Backend unavailable or returned an invalid response.';

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

	function updateBoard() {
		ground?.set({
			fen: currentPuzzle?.fen ?? startingFen,
			viewOnly: true
		});
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
			currentSession = await responseJson<SessionPayload>(response);
			currentIndex = 0;
			updateBoard();
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
			currentSession = await responseJson<SessionPayload>(response);
			currentIndex = 0;
			updateBoard();
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
				viewOnly: true
			});
		}

		void loadSessions();

		return () => {
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
					disabled={sessionLoading}
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
								disabled={sessionLoading}
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
						<h2 class="mt-1 text-2xl font-semibold tracking-tight">Puzzle {currentPuzzle.position} of {currentSession.puzzles.length}</h2>
					</div>
					<div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
						<span>{currentSession.completed}/{currentSession.puzzles.length} recorded</span>
						<span>Rating: {currentPuzzle.rating}</span>
						<span>Themes: {currentPuzzle.themes}</span>
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
